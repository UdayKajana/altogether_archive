import argparse
import logging
from typing import NamedTuple, Iterator, Optional
import apache_beam as beam
import json
import apache_beam.io.gcp.spanner as sp
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.io.gcp.pubsub import ReadFromPubSub
from typing import NamedTuple
from google.cloud import spanner
from apache_beam import coders
import json
import avro.io as avro_io
import avro.schema
from io import BytesIO
from avro.datafile import DataFileReader, DataFileWriter
import io
import logging
import argparse
from subprocess import getoutput
from google.cloud import bigquery
from concurrent import futures
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.types import (LimitExceededBehavior, PublisherOptions, PublishFlowControl,)

class TemplateOptions(PipelineOptions):
    @classmethod
    def _add_argparse_args(cls, parser):
        parser.add_value_provider_argument('--params', type=str)
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, help='Project ID')
    parser.add_argument('--runner', default="DataflowRunner", help='Pipeline runner')
    parser.add_argument('--region', default="us-east4", help='GCP project region')
    parser.add_argument('--staging_location', required=True, help='Staging GCS bucket path')
    parser.add_argument('--temp_location', required=True, help='Temp GCS bucket path')
    parser.add_argument('--template_location', required=True, help='GCS bucket path to save template')
    parser.add_argument('--pubsub_subscription_name', required=True, help='Input Subscription')
    parser.add_argument('--pubsub_topic', required=True, help='Output Topic')
    parser.add_argument('--sdk_container_image', default='us-east4-docker.pkg.dev/vz-it-np-gudv-dev-vzntdo-0/vznet/wireline:1.0.0', help='sdk_container_image location')
    parser.add_argument('--spanner_dataset', required=True, help='spanner dataset')
    parser.add_argument('--spanner_instance', required=True, help='spanner instance')
    parser.add_argument('--spanner_project', required=True, help='spanner project')
    parser.add_argument('--spanner_table', required=True, help='spanner table')
    parser.add_argument('--bq_project', required=True, help='bq project')
    parser.add_argument('--bq_dataset', required=True, help='bq dataset')
    parser.add_argument('--bq_table', required=True, help='bq table')
    parser.add_argument('--expansion_service', default='localhost:50768', help='Expansion service host:port')
    return parser.parse_known_args()
known_args, beam_args = parse_arguments()

logging.getLogger().setLevel(logging.INFO)

class DecodeAvroRecords(beam.DoFn):
    def process(self, element) -> Iterator[dict]:
        import avro.io as avro_io
        import avro.schema
        from io import BytesIO
        import time

        def reformat_input_msg_schema(msg):
            fmt_msg = {}
            fmt_msg['timestamp'] = msg['timestamp']
            fmt_msg['host'] = msg['host']
            fmt_msg['src'] = msg['src']
            fmt_msg['ingressTimestamp'] = msg['_event_ingress_ts']
            fmt_msg['origins'] = [msg['_event_origin']]
            tags_len = len(msg['_event_tags'])
            if tags_len > 0:
                if msg['_event_tags'][0] != "" and msg['_event_tags'][0] is not None:
                    fmt_msg['tags'] = msg['_event_tags']
                else:
                    fmt_msg['tags'] = ['Dummy']
            else:
                fmt_msg['tags'] = ['Dummy']
            fmt_msg['route'] = 3
            fmt_msg['fetchTimestamp'] = int(time.time() * 1000)
            fmt_msg['rawdata'] = msg['rawdata']
            
            return json.loads(fmt_msg['rawdata'])

        message: dict = {}
        raw_schema = """{"namespace": "com.vz.vznet",
                        "type": "record",
                        "name": "VznetDefault",
                        "doc": "Default schema for events in transit",
                        "fields": [
                        {"name": "timestamp", "type": "long"},
                        {"name": "host", "type": "string"},
                        {"name": "src",  "type": "string" },
                        {"name": "_event_ingress_ts", "type": "long"},
                        {"name": "_event_origin", "type": "string"},
                        {"name": "_event_tags", "type": {"type": "array", "items": "string"}},
                        {"name": "_event_route", "type": "string"},
                        {"name": "_event_metrics", "type": ["null", "bytes"], "default": null},
                        {"name": "rawdata", "type": "bytes"}
                        ]}"""
        try:
            schema = avro.schema.parse(raw_schema)
            avro_reader = avro_io.DatumReader(schema)
            avro_message = avro_io.BinaryDecoder(BytesIO(element))
            message = avro_reader.read(avro_message)
            
            if schema.name == 'VznetDefault':
                message['rawdata'] = message['rawdata'].decode("utf-8")
                message['_event_metrics'] = message['_event_metrics'].decode("utf-8") if message['_event_metrics'] is not None else None
                
            reformatted = reformat_input_msg_schema(message)
            yield reformatted
            
        except Exception as e:
            logging.error(f"Error processing message: {str(e)}")
            return

class RowMutation(NamedTuple):
    id: Optional[int]
    status: Optional[str]
    A: Optional[str]
    B: Optional[str]
    C: Optional[str]
coders.registry.register_coder(RowMutation, coders.RowCoder)

class SpannerWorkBench(beam.DoFn):
    def __init__(self, project_id, instance_id, database_id, table_name, pubsub_topic_id, bq_project, bq_dataset, bq_table):
        self.project_id = project_id
        self.instance_id = instance_id
        self.database_id = database_id
        self.table_name = table_name
        self.bq_project = bq_project
        self.bq_table = bq_table
        self.bq_dataset = bq_dataset
        self.client = None
        self.publisher = None
        self.bq_client = None 
        self.pubsub_topic_id = pubsub_topic_id

    def setup(self):
        self.client = spanner.Client(project=self.project_id)
        self.instance = self.client.instance(self.instance_id)
        self.database = self.instance.database(self.database_id)
        self.publisher = pubsub_v1.PublisherClient()
        self.bq_client = bigquery.Client(project=self.bq_project)

    def process(self, element):
        results = self.query_spanner(f"SELECT status FROM {self.table_name} WHERE id = {element.id} limit 1")
        status = results.get('status') if results else None
        if element.status == 'DELETE':
            self.execute_update_query(f"DEETE from {self.table_name} where id = {element.id}")
        elif not status or status=='ACTIVE':
            logging.log(logging.INFO, "New record is being inserted..." if status else "Data is being updated")
            self.insert_record(element)
        if status and status == 'TERMINATED':
            logging.log(logging.INFO, "Data is being saven in BQ and PubSub...")
            self.insert_rows_bigquery(element)
            self.pushToTopic(element)

    def query_spanner(self, query):
        with self.database.snapshot() as snapshot:
            results = snapshot.execute_sql(query)
            first_row = None
            try:
                first_row = next(iter(results))
            except StopIteration:
                return None
            if first_row:
                if results.metadata and results.metadata.row_type and results.metadata.row_type.fields:
                    field_names = [field.name for field in results.metadata.row_type.fields]
                    return dict(zip(field_names, first_row))
                else:
                    print("Warning: Could not retrieve column names from query metadata.")
                    return {"row_data": list(first_row)}
            return None
    
    def insert_record(self,element):
        try:
            with self.database.batch() as batch:
                batch.insert(
                    table=self.table_name,
                    columns= element.keys(),
                    values=[tuple(element.values)])
            logging.info(f"Inserted new record")
            return True
        except Exception as e:
            return False

    def update_data(self, transaction, updt_dt):
        rc = transaction.execute_update(updt_dt)
        return rc

    def execute_update_query(self, updt_dt):
        rc = self.database.run_in_transaction(self.update_data, updt_dt)
        print(f'the query updated {rc} records!')
    
    def EncodeAvro(self, element):
        def encode(data: dict) -> bytes:
            schema = """{"namespace": "com.vz.vznet", "type": "record", "name": "VznetDefault", "doc": "Default schema for events in transit", "fields": [ {"name": "timestamp", "type": "long"}, {"name": "host", "type": "string"}, {"name": "src",  "type": "string" }, {"name": "_event_ingress_ts", "type": "long"}, {"name": "_event_origin", "type": "string"}, {"name": "_event_tags", "type": {"type": "array", "items": "string"}}, {"name": "_event_route", "type": "string"}, {"name": "_event_metrics", "type": ["null", "bytes"], "default": null}, {"name": "rawdata", "type": "bytes"} ] }"""
            if isinstance(schema, dict):
                schema = json.dumps(schema)
            if isinstance(data, str):
                data = json.loads(data)
            schema: str = avro.schema.parse(schema)
            val = data
            datum_writer: avro_io.DatumWriter = avro_io.DatumWriter(schema)
            bytes_writer: io.BytesIO = io.BytesIO()
            encoder: avro_io.BinaryEncoder = avro_io.BinaryEncoder(bytes_writer)
            datum_writer.write(val, encoder)
            raw_bytes: bytes = bytes_writer.getvalue()
            return raw_bytes

        raw_data = element['rawdata']
        final_dict = {}
        final_dict['timestamp'] = element['timestamp']
        final_dict['src'] = element['src']
        final_dict['host'] = element['host']
        final_dict['_event_ingress_ts'] = element['ingressTimestamp']
        final_dict['_event_origin'] = '|'.join(element['origins'])
        final_dict["rawdata"] = json.dumps(raw_data)
        final_dict['_event_tags'] = element['tags']
        final_dict['_event_route'] = str(element['route'])
        final_dict['_event_metrics'] = None
        final_dict["rawdata"] = bytes(json.dumps(raw_data), 'utf-8')
        return encode(final_dict)
    
    def pushToTopic(self, data_rows):
        topic_path = self.publisher.topic_path(self.project_id, self.pubsub_topic_id)
        publish_futures = []
        def callback(publish_future: pubsub_v1.publisher.futures.Future) -> None:
            message_id = publish_future.result()
        publish_future = self.publisher.publish(topic_path, data_rows)
        publish_future.add_done_callback(callback)
        publish_futures.append(publish_future)
        print(f"Published messages with flow control settings to {topic_path}.")
    
    def saveDataInBQ(self, data):
        client = bigquery.Client(project=self.project_id)
        table_ref = client.dataset(self.dataset_id).table(self.table_name)
        if isinstance(data, dict):
            rows_to_insert = [data]
        elif isinstance(data, list):
            rows_to_insert = data
        try:
            table = client.get_table(table_ref)
            print(f"Table {table.project}.{table.dataset_id}.{table.table_id} found.")
            errors = client.insert_rows_json(table, data)
            if not errors:
                print(f"{len(data)} new rows have been added to {self.dataset_id}.{self.table_id}.")
            else:
                print("Encountered errors while inserting rows:")
                for error in errors:
                    print(f"Error: {error['errors']}")
                    print(f"Row data: {error['row']}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    
    def insert_rows_bigquery(self, rows_to_insert):
        table_ref = self.client.dataset(self.dataset_id).table(self.table_id)
        try:
            print(f"Inserting {len(rows_to_insert)} rows into '{self.project_id}.{self.bq_dataset}.{self.bq_table}'...")
            errors = self.bq_client.insert_rows_json(table_ref, rows_to_insert)
            if not errors:
                print("New rows have been added successfully.")
            else:
                print("Encountered errors while inserting rows:")
                for error_entry in errors:
                    print(f"  Row index {error_entry['index']}: {error_entry['errors']}")
        except Exception as e:
            print(f"Error inserting rows into BigQuery table: {e}")

options = {
    'project': known_args.project,
    'runner': known_args.runner,
    'region': known_args.region,
    'staging_location': known_args.staging_location,
    'temp_location': known_args.temp_location,
    'template_location': known_args.template_location,
    'save_main_session': True,
    'streaming': True,
    'sdk_container_image': known_args.sdk_container_image,
    'sdk_location': 'container'
}

pipeline_options = PipelineOptions.from_dictionary(options)
template_options = pipeline_options.view_as(TemplateOptions)
with beam.Pipeline(options=pipeline_options) as p:
    data = (p 
            | "Read From Pubsub" >> ReadFromPubSub( subscription=f"{known_args.pubsub_subscription_name}")
            | "Decode Avro"      >> beam.ParDo(DecodeAvroRecords()))
    ____ = data | "Process Messages" >> beam.ParDo(
                SpannerWorkBench(
                    project_id ='vz-it-np-jpuv-dev-anpdo-0',
                    instance_id='anp-spanner-instance',
                    database_id='network_wls_model',
                    table_name= 'streaming_pivote',
                    pubsub_topic_id = 'sanner_topic',
                    bq_project= 'vz-it-np-gudv-dev-dtwndo-0',
                    bq_table= 'streaming_pivote',
                    bq_dataset= 'uk_dag_inventory_work'
                ))
    #project_id, instance_id, database_id, table_name, pubsub_topic_id, bq_table, bq_dataset
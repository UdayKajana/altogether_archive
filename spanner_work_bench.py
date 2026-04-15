from google.cloud import spanner
import logging
import json

class SpannerWorkBench:
    def __init__(self, project_id, instance_id, database_id, table_name):
        self.project_id = project_id
        self.instance_id = instance_id
        self.database_id = database_id
        self.spanner_client = spanner.Client(project=self.project_id)
        self.instance = self.spanner_client.instance(self.instance_id)
        self.database = self.instance.database(self.database_id)
        self.table_name = table_name
        logging.info(f"Initialized SpannerOperations for database: {self.database_id}")

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

    def insert_record(self, record_id, data):
        try:
            with self.database.batch() as batch:
                batch.insert(
                    table=self.table_name,
                    columns=['id', 'status', 'A', 'B', 'C'],
                    values=[(
                        record_id,
                        data.get('status', ''),
                        data.get('A', ''),
                        data.get('B', ''),
                        data.get('C', '')
                    )]
                )
            logging.info(f"Inserted new record with ID: {record_id}")
            return True
        except Exception as e:
            return False

    def update_record(self, record_id, data):
        cols = list(data.keys())
        vals = list()
        for i in cols:
            vals.append(data.get(i))
        cols.append('id')
        vals.append(record_id)
        print(cols,vals)

        with self.database.batch() as batch:
            batch.update(
                table=self.table_name,
                columns=cols,
                values=[tuple(vals)]
            )
        logging.info(f"Updated record with ID: {record_id}")
        return True

    def delete_record(self, record_id):
        with self.database.batch() as batch:
            batch.delete(
                table=self.table_name,
                keyset=[record_id]
            )
        logging.info(f"Deleted record with ID: {record_id}")
        return True

    def process_message(self, message_json):
        try:
            message = json.loads(message_json)
            record_id = message.get('id')
            data = message.get('data', {})

            if not record_id:
                logging.warning("Message missing ID, discarding: %s", message)
                return {"error": "Missing ID in message"}
            record = self.query_record(record_id)

            if record:
                if record.get('status') == 'ACTIVE':
                    self.update_record(record_id, data)
                    return {
                        'id': record_id,
                        'action': 'updated',
                        'previous_status': record.get('status'),
                        'data': data
                    }
                else:
                    logging.info(f"Record {record_id} exists but status is {record.get('status')}, not updating")
                    return {
                        'id': record_id,
                        'action': 'skipped',
                        'status': record.get('status')
                    }
            else:
                self.insert_record(record_id, data)
                return {
                    'id': record_id,
                    'action': 'inserted',
                    'data': data
                }

        except Exception as e:
            logging.error(f"Error processing message: {message_json}. Error: {str(e)}")
            return {
                'error': str(e),
                'message': message_json
            }

    def update_data(self, transaction, updt_dt):
        rc = transaction.execute_update(updt_dt)
        return rc

    def execute_update_query(self, updt_dt):
        rc = self.database.run_in_transaction(self.update_data, updt_dt)
        print(f'the query updated {rc} records!')

if __name__ == "__main__":
    spanner_ops = SpannerWorkBench(
        project_id='vz-it-np-jpuv-dev-anpdo-0',
        instance_id='anp-spanner-instance',
        database_id='network_wls_model',
        table_name='streaming_pivote'
    )
    cnt = spanner_ops.query_spanner("SELECT status FROM streaming_pivote where id = 100 limit 1")
    print(cnt.get('status') if cnt else None)

    # query_data('', '','SELECT run_key,score_model_id FROM nqes_site_scores_32 limit 5')
    # message = json.dumps({
    #     'id': 'user456',
    #     'data': {
    #         'name': 'John Doe',
    #         'status': 'ACTIVE'
    #     }
    # })
    # result = spanner_ops.process_message(message)
    # print(f"Process result: {result}")
    # update_result = spanner_ops.conditional_update(
    #     'user789', 
    #     {'name': 'Jane Smith'}
    # )
    # print(f"Conditional update result: {update_result}")
    # for i in range(10):
    #     try:
    #         spanner_ops.insert_record(i+1,{'status':'ACTIVE','A':f'{i+1}','B':f'{i+1}','C':f'{i+1}'})
    #     except Exception as e:
    #         print("Error inserting :",e)
    # for i in range(10):
    #     record = spanner_ops.query_record(i+1)
    #     print(f"Query result: {record}")
    # print(spanner_ops.update_record(1, {'status':'ACTIVE','A':'a','B':'b'}))
    # print(spanner_ops.query_record(1))
    spanner_ops.query_spanner("select * from streaming_pivote")
    spanner_ops.execute_update_query("UPDATE streaming_pivote SET C='C' WHERE id=10")

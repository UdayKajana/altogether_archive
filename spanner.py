import os
from google.cloud import spanner
network_wls_model_db =  "network_wls_model"
network_wls_curated_db = "network_wls_curated" 
wireline_churn_db = "wireline_churn"
def execute_ddl(db, sql):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "/home/sL_dtwin/.sak/sa-dev-gudv-app-dtwndo-0_key.json"
    project = 'vz-it-np-jpuv-dev-anpdo-0'
    instance_id = "anp-spanner-instance"
    client = spanner.Client(project=project)
    instance = client.instance(instance_id)
    database = instance.database(db)
    for i in sql:
        try:
            operation = database.update_ddl([i])
            operation.result()
            print("Table delete/created successfully!")
        except Exception as e:
            print(f"Error creating table: {str(e)}")

updt_dt = '''UPDATE ug_customer_network_usage_anomalous_sites SET load_dt=DATE(created_timestamp) WHERE load_dt is null'''
def update_data(transaction):
    rc  = transaction.execute_update(updt_dt)
    return rc
def execute_update(db):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "/home/sL_dtwin/.sak/sa-dev-gudv-app-dtwndo-0_key.json"
    project = 'vz-it-np-jpuv-dev-anpdo-0'
    instance_id = "anp-spanner-instance"
    client = spanner.Client(project=project)
    instance = client.instance(instance_id)
    database = instance.database(db)
    rc = database.run_in_transaction(update_data)
    print(f'the query updated {rc} records!')
while True:
    db = input("Enterd DB (M/C/CH):")
    if db not in ("M","C","CH"):
        print("): invalid DB :(")
        continue
    sql = input("Enter Query:")
    database = None
    if db == "M":
        database = network_wls_model_db
    elif db == 'C':
        database = network_wls_curated_db
    else:
        database = wireline_churn_db
    if not sql:
        print("): No Query Given so No Results :(")
        execute_ddl(database,[sql])
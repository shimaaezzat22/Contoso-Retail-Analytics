import os
import uuid

# ---------------------------------------------------------
# 1. CONFIGURATION: SET YOUR PATHS
# ---------------------------------------------------------
base_dir = os.path.dirname(os.path.abspath(__file__))
tables_dir = os.path.join(base_dir, "tables")

fact_files = {
    "fact_vExchangeRate": "Fact ExchangeRate",
    "fact_vCustomerAcquisition": "Fact CustomerAcquisition",
    "fact_vCustomerSurvey": "Fact CustomerSurvey",
    "fact_vInventory": "Fact Inventory",
    "fact_vMarketingSpend": "Fact MarketingSpend",
    "fact_vOnlineSales": "Fact OnlineSales",
    "fact_vOrderFulfillment": "Fact OrderFulfillment",
    "fact_vOrderPayment": "Fact OrderPayment",
    "fact_vReturns": "Fact Returns",
    "fact_vSalesQuota": "Fact SalesQuota",
    "fact_vStoreSales": "Fact StoreSales"
}

dim_files = {
    "dim_vAcquisitionChannel": "Dim AcquisitionChannel",
    "dim_vChannel": "Dim Channel",
    "dim_vCurrency": "Dim Currency",
    "dim_vEmployee": "Dim Employee",
    "dim_vDate": "Dim Date",
    "dim_vPaymentMethod": "Dim PaymentMethod",
    "dim_vCustomer": "Dim Customer",
    "dim_vProduct": "Dim Product",
    "dim_vPromotion": "Dim Promotion",
    "dim_vReturnReason": "Dim ReturnReason",
    "dim_vStore": "Dim Store"
}

# ---------------------------------------------------------
# 2. DEFENSIVE CHECKS
# ---------------------------------------------------------
if not os.path.exists(tables_dir):
    raise NotADirectoryError(f"CRITICAL: Tables directory not found at {tables_dir}. Check your path.")

# ---------------------------------------------------------
# 3. DRY ARCHITECTURE: THE GENERATOR FUNCTION
# ---------------------------------------------------------
def generate_tmdl(file_key, table_name, query_group, m_function):
    lineage_tag = str(uuid.uuid4())
    
    # Restored the correct native deep-indent expression syntax.
    # NO tabs. NO backticks. 
    return (
        f"table '{table_name}'\n"
        f"\tlineageTag: {lineage_tag}\n\n"
        f"\tpartition '{table_name}' = m\n"
        f"\t\tmode: import\n"
        f"\t\tqueryGroup: '{query_group}'\n"
        f"\t\tsource = ```\n"
        f"\t\t\tlet\n"
        f"\t\t\t\tFileRow = DataSource{{[Name=\"{file_key}.parquet\"]}},\n"
        f"\t\t\t\tBinaryData = FileRow[Content],\n"
        f"\t\t\t\tProcessedData = {m_function}(BinaryData, \"{file_key}.parquet\")\n"
        f"\t\t\tin\n"
        f"\t\t\t\tProcessedData\n\t\t\t```\n"
    )

def deploy_tables(file_dict, query_group, m_function):
    print(f"Deploying {len(file_dict)} tables to '{query_group}'...")
    for k, v in file_dict.items():
        tmdl_content = generate_tmdl(k, v, query_group, m_function)
        file_path = os.path.join(tables_dir, f"{v}.tmdl")
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tmdl_content)
        print(f"  [+] Generated: '{v}.tmdl'")

# ---------------------------------------------------------
# 4. EXECUTION
# ---------------------------------------------------------
deploy_tables(fact_files, "Loaded Facts", "fxLoadFactParquet")
print("-" * 40)
deploy_tables(dim_files, "Loaded Dimensions", "fxLoadDimParquet")

print(f"\nDEPLOYMENT COMPLETE. Generated {len(fact_files) + len(dim_files)} total files.")
print("Switch back to Power BI Desktop and hit 'Apply changes'.")
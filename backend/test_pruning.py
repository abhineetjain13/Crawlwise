import sqlite3
import json
from app.services.crawl_service import _build_llm_discovered_sources
from app.services.discover.service import DiscoveryManifest
from app.services.extract.spa_pruner import prune_spa_state

def run_test():
    with sqlite3.connect('crawlerai.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, source_url, discovered_data FROM crawl_records WHERE source_url LIKE '%digikey%' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    
    if not row:
        print("No digikey row found")
        return
        
    id, url, discovered_data_json = row
    print("Testing record ID:", id, "URL:", url)
    
    discovered_data = json.loads(discovered_data_json or "{}")
    
    manifest = DiscoveryManifest()
    manifest.next_data = discovered_data.get("next_data")
    manifest._hydrated_states = discovered_data.get("hydrated_states")
    manifest.embedded_json = discovered_data.get("embedded_json")
    manifest.json_ld = discovered_data.get("json_ld", [])
    manifest.microdata = discovered_data.get("microdata", [])
    manifest.network_payloads = discovered_data.get("network_payloads", [])
    
    # Prune it directly for logging
    pruned = prune_spa_state(manifest.next_data)
    
    # Run through the build pipeline
    llm_payload = _build_llm_discovered_sources({}, manifest)
    llm_json = json.dumps(llm_payload, indent=2)
    
    with open("prune_test_out.txt", "w") as f:
        f.write("--- ORIGINAL NEXT DATA LENGTH ---\n")
        f.write(str(len(json.dumps(manifest.next_data))) + " chars\n\n")
        f.write("--- PRUNED NEXT DATA LENGTH ---\n")
        f.write(str(len(json.dumps(pruned))) + " chars\n\n")
        f.write("--- LLM SNAPSHOT LENGTH ---\n")
        f.write(str(len(llm_json)) + " chars\n\n")
        f.write("--- DOES IT CONTAIN QUANTITY TABLE? ---\n")
        qtable = "quantityTable" in llm_json or "multiples" in llm_json
        f.write(str(qtable) + "\n\n")
        f.write("--- LLM PAYLOAD CONTENT ---\n")
        f.write(llm_json)

    print("Wrote results to prune_test_out.txt")
    print(f"Contains quantity table: {qtable}")

if __name__ == "__main__":
    run_test()

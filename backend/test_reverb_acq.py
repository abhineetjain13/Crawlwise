import asyncio
import logging
from app.services.crawl_service import process_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def main():
    try:
        from app.database import AsyncSessionLocal
        # We need a run record. It's easier to just call acquire directly
        from app.services.acquisition.acquirer import AcquisitionRequest, acquire
        
        result = await acquire(
            AcquisitionRequest(
                run_id=42,
                url="https://reverb.com/marketplace?product_type=electric-guitars",
                surface="listing",
            )
        )
        print("Acquisition result:", result.method)
        print("HTML length:", len(result.html))
    except Exception as e:
        print("Error:", type(e), e)

if __name__ == "__main__":
    asyncio.run(main())

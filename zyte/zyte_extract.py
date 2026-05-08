"""Extract product data from TEST_SITES.md URLs using Zyte API."""

import json
import os
import sys
import time
from pathlib import Path

import requests

URLS = [
    "https://www.sneakersnstuff.com/products/dime-soft-rock-crewneck-dime2sp2542blk",
    "https://www.samsclub.com/ip/Scotch-Heavy-Duty-Shipping-Packaging-Tape-Dispensers-1-88-x-27-7-yd-6-Pack/5113185138?classType=REGULAR",
    "https://www.goat.com/sneakers/dunk-low-black-white-dd1391-100",
    "https://stockx.com/nike-dunk-low-retro-white-black-2021",
    "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
    "https://www.amazon.com/dp/B08J5F3G18",
    "https://www.apple.com/shop/buy-iphone/iphone-16",
    "https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000",
    "https://www.farfetch.com/in/shopping/men/philipp-plein-leather-disco-biker-jacket-item-18497263.aspx",
    "https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301",
    "https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1",
    "https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742#lnk=sametab",
    "https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/604342441",
    "https://www.lowes.com/pd/Minka-Lavery-Lansdale-Sand-Black-Transitional-Opal-Glass-Lantern-Pendant-Light/1001420790",
    "https://www.homedepot.com/p/MSI-Yellow-Pebbles-12-in-x-12-in-Polished-Quartzite-Floor-and-Wall-Tile-10-sq-ft-case-LPEBMYEL1212POL/202515091",
    "https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035",
    "https://www.dickssportinggoods.com/p/birkenstock-womens-arizona-big-buckle-soft-footbed-sandals-25birwcasuwrznbgbcegp/25birwcasuwrznbgbcegp?color=Sandcastle",
    "https://www.jdsports.co.uk/product/pink-adidas-originals-classic-shorts/19741988/",
    "https://shop.lululemon.com/p/men-joggers/ABC-Jogger/_/prod8530240",
    "https://in.puma.com/in/en/pd/speedcat-sneakers/406329?swatch=02",
    "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    "https://www.sephora.com/product/colorful-eyeshadow-P515026?skuId=2820108&icid2=products%20grid:p515026:product",
    "https://www.zappos.com/kratos/p/womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988?zlfid=191&ref=pd_search_nr-1-bqcp_1",
    "https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords?ID=19116329&swatchColor=Black",
    "https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html",
    "https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084#colourWayId-210397088",
    "https://www.wayfair.com/furniture/pdp/flexsteel-bryce-power-reclining-sofa-with-power-headrest-xtya1522.html?piid=94673717&auctionId=db4b38eb-7955-4fc9-8d81-0dae00f68111&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22db4b38eb-7955-4fc9-8d81-0dae00f68111%22}&adTypeId=1",
    "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html?v1=527078510",
    "https://us.frankbody.com/products/original-coffee-scrub",
    "https://colourpop.com/products/going-coconuts-eyeshadow-palette",
    "https://www.fashionnova.com/products/just-vibes-strapless-pant-set-yellow?recommendationAttributionId=error-nosto-1-fallback-nosto-1-copy-1720644688978",
    "https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet?pr_prod_strat=e5_desc&pr_rec_id=3ef961ba9&pr_rec_pid=7216396632150&pr_ref_pid=7559267778646&pr_seq=uniform&variant=41298450153558",
    "https://www.untuckit.com/collections/shirts/products/cameron-wr-2",
    "https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642",
    "https://www.thomann.de/gb/akg_k702.htm",
    "https://www.discogs.com/release/249504",
    "https://www.ifixit.com/products/iphone-16-plus-battery",
    "https://www.vitacost.com/vitacost-vitamin-d3-mini-gels",
    "https://www.rockler.com/rockler-table-saw-crosscut-sled",
    "https://www.backmarket.com/en-us/p/iphone-15-plus",
    "https://31philliplim.com/collections/the-luna-bag-1/products/luna-1",
    "https://zadig-et-voltaire.com/eu/uk/p/JMTS01771443/t-shirt-teddyx-blue-sixtine",
    "https://ar.puma.com/pd/zapatillas-mostro-ecstasy-unisex/397328.html?color=07",
    "https://www.karenmillen.com/eu/product/karen-millen-cotton-utility-button-detail-barrel-leg-trouser_bkk28382?colour=ivory",
    "https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
    "https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html",
    "https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html",
    "https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos/products/italian-seersucker-sutton-suit-2",
    "https://savannahs.com/collections/all-boots/products/pavlova-100-lace-up-blush-satin-boots-cl28517s",
    "https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants?g_aidx=Listing_by_listing_quality_production&g_aqid=dcff41da6c7483961c0b500769d4c7bc",
    "https://www.desertcart.in/products/808107894-hormone-healthy-eats-100-recipes-to-balance-your-hormones-support?source=search",
]


def extract_product(url: str, api_key: str) -> dict:
    """Call Zyte API for a single product URL."""
    endpoint = "https://api.zyte.com/v1/extract"
    auth = (api_key, "")
    payload = {
        "url": url,
        "product": True,
        "browserHtml": False,
    }
    resp = requests.post(endpoint, json=payload, auth=auth, timeout=120)
    resp.raise_for_status()
    return resp.json()


def main():
    api_key = os.environ.get("ZYTE_API_KEY")
    if not api_key:
        print("ERROR: Set ZYTE_API_KEY environment variable.")
        sys.exit(1)

    out_path = Path("zyte_extracted_results.json")
    results = []

    for i, url in enumerate(URLS, start=1):
        print(f"[{i}/{len(URLS)}] {url}")
        try:
            data = extract_product(url, api_key)
            results.append({"url": url, "status": "ok", "data": data})
            print(f"  -> ok ({len(json.dumps(data))} bytes)")
        except Exception as exc:
            print(f"  FAILED: {exc}")
            results.append({"url": url, "status": "error", "error": str(exc)})
        # write partial results after every URL so progress is visible
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(results)} records to {out_path}")


if __name__ == "__main__":
    main()

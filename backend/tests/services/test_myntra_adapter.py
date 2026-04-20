from __future__ import annotations

import pytest

from app.services.adapters.myntra import MyntraAdapter


@pytest.mark.asyncio
async def test_myntra_adapter_extracts_listing_cards_from_dom() -> None:
    html = """
    <html>
      <body>
        <script>
          window.__myx = {
            "searchData": {
              "results": {
                "products": [
                  {
                    "productId": 20510856,
                    "productName": "Mamaearth Vitamin C Daily Glow Face Cream",
                    "brand": "Mamaearth",
                    "landingPageUrl": "day-cream/mamaearth/mamaearth-vitamin-c-daily-glow-face-cream-with-vitc--turmeric-for-skin-illumination-150g/20510856/buy",
                    "searchImage": "https://assets.myntassets.com/a.jpg",
                    "price": 351,
                    "mrp": 399,
                    "sizes": "100-150 ML",
                    "rating": 4.3,
                    "ratingCount": 11900
                  }
                ]
              }
            }
          };
        </script>
        <ul class="results-base">
          <li id="20510856" class="product-base">
            <a href="day-cream/mamaearth/mamaearth-vitamin-c-daily-glow-face-cream-with-vitc--turmeric-for-skin-illumination-150g/20510856/buy">
              <div class="product-productMetaInfo">
                <h3 class="product-brand">Mamaearth</h3>
                <h4 class="product-product">Vit. C Daily Glow Cream 150g</h4>
                <h4 class="product-sizes">Sizes: 100-150 ML</h4>
                <div class="product-price">
                  <span class="product-discountedPrice">Rs. 351</span>
                  <span class="product-strike">Rs. 399</span>
                </div>
              </div>
            </a>
          </li>
          <li id="31145778" class="product-base">
            <a href="day-cream/asaya/asaya-even-evermore-cream-with-alpha-arbutin--ceramides---50g/31145778/buy">
              <div class="product-productMetaInfo">
                <h3 class="product-brand">Asaya</h3>
                <h4 class="product-product">Even Evermore Cream - 50g</h4>
                <h4 class="product-sizes">Sizes: 40-50gm</h4>
                <div class="product-price">
                  <span class="product-discountedPrice">Rs. 449</span>
                  <span class="product-strike">Rs. 599</span>
                </div>
              </div>
            </a>
          </li>
        </ul>
      </body>
    </html>
    """

    adapter = MyntraAdapter()

    result = await adapter.extract(
        "https://www.myntra.com/face-moisturisers",
        html,
        "ecommerce_listing",
    )

    assert len(result.records) == 2
    assert result.records[0]["brand"] == "Mamaearth"
    assert result.records[0]["image_url"] == "https://assets.myntassets.com/a.jpg"
    assert result.records[0]["url"].endswith("/20510856/buy")
    assert result.records[1]["title"] == "Even Evermore Cream - 50g"

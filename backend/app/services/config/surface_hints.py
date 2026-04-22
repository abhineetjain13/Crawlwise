from __future__ import annotations

SURFACE_DETAIL_PATH_HINTS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "/dp/", "/p/", "/pd/",
        "/proddetail/",
        "/product", "/products/", "/item/",
        "/produit/", "/produits/",
        "/produkt/", "/produkte/",
        "/producto/", "/productos/",
        "/prodotto/", "/prodotti/",
        "/seihin/", "/shohin/",
        "/artikel/",
        "/articulo/",
        "/merchandise/",
        "/goods/",
        "/sku/",
        "/detail/",
        "/buy/",
        "/shop/",
    ),
    "job": (
        "/job", "/jobs", "/career", "/careers",
        "/position", "/posting", "/opening",
        "/emploi/", "/offres-demploi/",
        "/stelle/", "/stellenangebot/",
        "/empleo/", "/ofertas-de-empleo/",
        "/lavoro/", "/offerte-di-lavoro/",
        "/kyuujin/", "/shigoto/",
        "/vacancy/", "/vacatures/",
        "/recruitment/",
    ),
}


def surface_group(surface: str | None) -> str | None:
    normalized = str(surface or "").strip().lower()
    if normalized.startswith("ecommerce_"):
        return "ecommerce"
    if normalized.startswith("job_"):
        return "job"
    return None


def detail_path_hints(surface: str | None = None) -> tuple[str, ...]:
    group = surface_group(surface)
    if group:
        return SURFACE_DETAIL_PATH_HINTS.get(group, ())
    merged: list[str] = []
    for hints in SURFACE_DETAIL_PATH_HINTS.values():
        for hint in hints:
            if hint not in merged:
                merged.append(hint)
    return tuple(merged)


__all__ = [
    "SURFACE_DETAIL_PATH_HINTS",
    "detail_path_hints",
    "surface_group",
]

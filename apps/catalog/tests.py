from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.filters import descendant_category_ids
from apps.inventory.models import StockReservation
from apps.inventory.services import reserve_cart
from apps.testing import fill_cart, make_category, make_user, make_variant


class CategoryFilterTests(TestCase):
    def setUp(self):
        self.skin = make_category("Skincare")
        self.serums = make_category("Sérums", parent=self.skin)
        self.vitc = make_category("Vitamina C", parent=self.serums)  # nivel 3
        self.makeup = make_category("Maquillaje")
        self.lips = make_category("Labios", parent=self.makeup)
        self.p_skin = make_variant(category=self.skin, name="Limpiador").product
        self.p_serum = make_variant(category=self.serums, name="Sérum hidratante").product
        self.p_vitc = make_variant(category=self.vitc, name="Sérum vitamina c").product
        self.p_lips = make_variant(category=self.lips, name="Gloss labial").product

    def test_home_shows_at_most_ten_featured_products_and_links_to_shop(self):
        for index in range(7):
            make_variant(category=self.skin, name=f"Producto destacado {index}")

        response = self.client.get(reverse("catalog:home"))

        self.assertEqual(len(response.context["featured_products"]), 10)
        self.assertContains(response, f'href="{reverse("catalog:shop")}">ver todos los productos')

    def test_home_category_carousel_shows_all_visible_categories_without_follow_link(self):
        response = self.client.get(reverse("catalog:home"))

        self.assertEqual(response.context["categories"].count(), 5)
        self.assertContains(response, 'data-rail="categories"')
        self.assertNotContains(response, "síguenos")

    def test_product_detail_reflects_reservation_and_restores_expired_quantity(self):
        variant = self.p_skin.variants.first()
        user = make_user("reservador")
        reserve_cart(user, fill_cart(user, (variant, 2)))

        response = self.client.get(self.p_skin.get_absolute_url())
        self.assertEqual(response.context["variants"][0].available_quantity, 3)
        self.assertContains(response, "3 unidades disponibles")

        StockReservation.objects.filter(user=user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = self.client.get(self.p_skin.get_absolute_url())
        self.assertEqual(response.context["variants"][0].available_quantity, 5)
        self.assertContains(response, "5 unidades disponibles")

    def names(self, response):
        return {p.name for p in response.context["page_obj"]}

    def test_category_page_includes_all_descendants(self):
        response = self.client.get(self.skin.get_absolute_url())
        self.assertEqual(self.names(response), {"Limpiador", "Sérum hidratante", "Sérum vitamina c"})

    def test_filter_by_subcategory_includes_its_descendants(self):
        response = self.client.get(self.skin.get_absolute_url(), {"cat": "serums"})
        self.assertEqual(self.names(response), {"Sérum hidratante", "Sérum vitamina c"})
        response = self.client.get(self.skin.get_absolute_url(), {"cat": "vitamina-c"})
        self.assertEqual(self.names(response), {"Sérum vitamina c"})

    def test_shop_filters_multiple_categories(self):
        url = reverse("catalog:shop")
        self.assertEqual(len(self.names(self.client.get(url))), 4)
        response = self.client.get(url + "?cat=labios&cat=vitamina-c")
        self.assertEqual(self.names(response), {"Gloss labial", "Sérum vitamina c"})
        self.assertEqual(response.context["category_filter"].selected, ["labios", "vitamina-c"])

    def test_unknown_slug_is_ignored(self):
        response = self.client.get(reverse("catalog:shop"), {"cat": "no-existe"})
        self.assertEqual(len(self.names(response)), 4)
        self.assertFalse(response.context["category_filter"].active)

    def test_inactive_category_and_product_are_hidden(self):
        self.lips.is_active = False
        self.lips.save()
        self.p_skin.is_active = False
        self.p_skin.save()
        names = self.names(self.client.get(reverse("catalog:shop")))
        self.assertNotIn("Gloss labial", names)
        self.assertNotIn("Limpiador", names)
        self.assertEqual(descendant_category_ids(self.makeup), [self.makeup.pk])

    def test_counts_roll_up(self):
        response = self.client.get(reverse("catalog:shop"))
        by_slug = {n.slug: n.count for top in response.context["category_filter"].nodes for n in top.walk()}
        self.assertEqual(by_slug["skincare"], 3)
        self.assertEqual(by_slug["serums"], 2)
        self.assertEqual(by_slug["maquillaje"], 1)

    def test_search_can_be_filtered_by_category(self):
        url = reverse("catalog:search")
        self.assertEqual(
            self.names(self.client.get(url, {"q": "sérum"})), {"Sérum hidratante", "Sérum vitamina c"}
        )
        response = self.client.get(url, {"q": "sérum", "cat": "vitamina-c"})
        self.assertEqual(self.names(response), {"Sérum vitamina c"})
        self.assertContains(response, 'name="q" value="sérum"')  # se conserva la búsqueda al filtrar

    def test_pagination_keeps_filters(self):
        for i in range(13):
            make_variant(category=self.lips, name=f"Labial {i:02d}")
        response = self.client.get(reverse("catalog:shop"), {"cat": "labios"})
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(response, "cat=labios&amp;page=2")

    def test_filter_ui_renders(self):
        response = self.client.get(reverse("catalog:shop"), {"cat": "serums"})
        self.assertContains(response, 'name="cat" value="serums" checked')
        self.assertContains(response, "limpiar filtros")

    def test_subcategory_of_inactive_parent_is_hidden(self):
        self.skin.is_active = False
        self.skin.save()
        names = self.names(self.client.get(reverse("catalog:shop")))
        self.assertEqual(names, {"Gloss labial"})  # sérums y vitamina C cuelgan de skincare
        self.assertEqual(self.client.get(self.skin.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(self.serums.get_absolute_url()).status_code, 404)

    def test_category_filter_never_shows_other_branches(self):
        # ?cat= de otra rama (maquillaje) se ignora dentro de skincare
        response = self.client.get(self.skin.get_absolute_url(), {"cat": "labios"})
        self.assertEqual(self.names(response), {"Limpiador", "Sérum hidratante", "Sérum vitamina c"})
        self.assertFalse(response.context["category_filter"].active)

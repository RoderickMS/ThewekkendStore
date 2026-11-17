"""
Filtros por categoría del catálogo (Etapa 2).

Se usa en la tienda completa, en cada categoría (sobre sus subcategorías, a
cualquier profundidad) y en los resultados de búsqueda. El filtro se aplica
siempre en el servidor con `?cat=<slug>&cat=<slug>`; los resultados son la
unión de las categorías elegidas y todos sus descendientes.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db.models import Count

from .models import Category, Product


@dataclass
class FilterNode:
    category: Category
    count: int = 0
    selected: bool = False
    children: list = field(default_factory=list)

    @property
    def slug(self):
        return self.category.slug

    @property
    def name(self):
        return self.category.name

    def descendant_ids(self):
        ids = [self.category.pk]
        for child in self.children:
            ids.extend(child.descendant_ids())
        return ids

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class CategoryFilter:
    products: object  # queryset ya filtrado
    nodes: list  # árbol de FilterNode para pintar los chips
    selected: list  # slugs elegidos (válidos)

    @property
    def active(self) -> bool:
        return bool(self.selected)


def visible_category_ids():
    """pk de las categorías visibles: activas y con toda su cadena de padres
    activa (una subcategoría activa dentro de una categoría desactivada no se
    muestra, igual que no aparece en el árbol de filtros)."""
    children_by_parent = defaultdict(list)
    for pk, parent_id in Category.objects.filter(is_active=True).values_list("pk", "parent_id"):
        children_by_parent[parent_id].append(pk)
    visible, frontier = [], children_by_parent[None]
    while frontier:
        visible.extend(frontier)
        frontier = [child for pk in frontier for child in children_by_parent[pk]]
    return visible


def base_products():
    """Productos visibles en la tienda: activos y con categoría visible."""
    return Product.objects.filter(is_active=True, category_id__in=visible_category_ids())


def descendant_category_ids(category):
    """pk de la categoría y de todas sus subcategorías activas (cualquier nivel)."""
    ids = [category.pk]
    frontier = [category.pk]
    while frontier:
        frontier = list(
            Category.objects.filter(parent_id__in=frontier, is_active=True).values_list(
                "pk", flat=True
            )
        )
        ids.extend(frontier)
    return ids


def _build_tree(root=None):
    """Árbol de categorías activas. Con `root`, devuelve las subcategorías de
    esa categoría; sin ella, todas las categorías raíz."""
    children_by_parent = defaultdict(list)
    for category in Category.objects.filter(is_active=True).order_by("order", "name"):
        children_by_parent[category.parent_id].append(category)

    def build(category):
        return FilterNode(category, children=[build(c) for c in children_by_parent[category.pk]])

    return [build(c) for c in children_by_parent[root.pk if root else None]]


def build_category_filter(request, products, root=None) -> CategoryFilter:
    """Aplica `?cat=` a `products` y arma el árbol de chips con contadores.

    `products` es el queryset base *sin* filtrar por categoría (para que los
    contadores muestren cuántos resultados daría cada categoría).
    """
    nodes = _build_tree(root)

    own_counts = Counter()
    for row in (
        Product.objects.filter(pk__in=products.order_by().values("pk"))
        .values("category_id")
        .annotate(n=Count("pk"))
    ):
        own_counts[row["category_id"]] = row["n"]

    def fill(node):
        node.count = own_counts[node.category.pk] + sum(fill(c) for c in node.children)
        return node.count

    for node in nodes:
        fill(node)

    valid = {n.slug: n for top in nodes for n in top.walk()}
    selected = []
    for slug in request.GET.getlist("cat"):
        if slug in valid and slug not in selected:
            selected.append(slug)
    for slug in selected:
        valid[slug].selected = True

    if selected:
        ids = set()
        for slug in selected:
            ids.update(valid[slug].descendant_ids())
        products = products.filter(category_id__in=ids)

    def prune(node_list):
        kept = []
        for node in node_list:
            node.children = prune(node.children)
            if node.count > 0 or node.selected or node.children:
                kept.append(node)
        return kept

    return CategoryFilter(products=products, nodes=prune(nodes), selected=selected)


def querystring_without_page(request) -> str:
    """Querystring actual sin `page`, para conservar filtros al paginar."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()

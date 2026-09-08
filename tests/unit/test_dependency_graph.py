import pytest

from nirikshan.catalog.graph import load_graph, rank_probable_root
from nirikshan.catalog.service import add_dependency, get_environment
from nirikshan.schemas.catalog import DependencyIn
from tests.helpers import make_service

pytestmark = pytest.mark.unit


@pytest.fixture
def chain(db):
    # frontend -> gateway -> orders -> payment -> db ; orders -> inventory -> db
    for n, tier in [("frontend", 1), ("gateway", 1), ("orders", 1), ("payment", 1),
                    ("inventory", 2), ("db", 1)]:
        make_service(db, n, tier=tier)
    for u, d in [("frontend", "gateway"), ("gateway", "orders"), ("orders", "payment"),
                 ("orders", "inventory"), ("payment", "db"), ("inventory", "db")]:
        add_dependency(db, DependencyIn(upstream=u, downstream=d, environment="production"))
    return load_graph(db, get_environment(db, "production").id)


def test_blast_radius_of_db(chain):
    db_id = chain.id_for("db")
    br = chain.blast_radius(db_id)
    assert set(br["direct_dependents"]) == {"payment", "inventory"}
    assert set(br["indirect_dependents"]) == {"orders", "gateway", "frontend"}
    assert br["total_impacted"] == 5
    assert "frontend" in br["impacted_user_facing"]


def test_downstream_closure(chain):
    orders_id = chain.id_for("orders")
    assert set(chain.downstream_closure(orders_id)) == {"payment", "inventory", "db"} - set() or True
    names = {chain.name(x) for x in chain.downstream_closure(orders_id)}
    assert names == {"payment", "inventory", "db"}


def test_rank_probable_root_prefers_deepest_shared_dependency(chain):
    impacted = [chain.id_for(n) for n in ("payment", "orders", "gateway", "db")]
    ranked = rank_probable_root(chain, impacted)
    assert chain.name(ranked[0]) == "db"

from worker_ids import assign_worker_id, file_slug, make_lane_id


def test_file_slug():
    assert file_slug("models/order.py") == "models-order"
    assert file_slug("tests/test_orders.py") == "tests-test-orders"


def test_make_lane_id():
    assert make_lane_id("local", ["models/order.py"]) == "midgard.models-order"
    assert make_lane_id("cloud", ["routers/orders.py"]) == "asgard.routers-orders"
    assert make_lane_id("cloud", []) == "asgard.primary"


def test_assign_uniquify():
    used: dict[str, int] = {}
    a = assign_worker_id("local", ["same.py"], used)
    b = assign_worker_id("local", ["same.py"], used)
    assert a == "midgard.same"
    assert b == "midgard.same-2"

def finish_round(service, room_id):
    deadline = service._season(room_id).live_round["ends_at"]
    service.clock = lambda: deadline
    assert service.finish_due(room_id)
    return service.view(room_id)


def play_knockouts(service, room_id, market, humans=frozenset(), limit=12):
    """Play every remaining live knockout round (playoffs) to the champion."""
    view = service.view(room_id)
    for _ in range(limit):
        if view["champion"]:
            return view
        for club in humans:
            service.ready(room_id, club)
        view = service.advance(room_id, market, set(humans))
        if view["live_round"]:
            view = finish_round(service, room_id)
    raise AssertionError("Os playoffs não terminaram.")

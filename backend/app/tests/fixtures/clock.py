def finish_round(service, room_id):
    deadline = service._season(room_id).live_round["ends_at"]
    service.clock = lambda: deadline
    assert service.finish_due(room_id)
    return service.view(room_id)

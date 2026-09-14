from scripts.research_betting_2025_2026 import Race, summary, tickets, winning_tickets


def sample_race() -> Race:
    return Race(
        year=2025,
        race_id=1,
        runners=(3, 7, 2, 9, 5, 4, 6, 1),
        p1=.40,
        p2=.22,
        meet_code=1,
        date="2025-01-03",
        payouts={
            "WIN": {"3": 2.0},
            "PLC": {"3": 1.2, "7": 1.3, "2": 2.0},
            "QNL": {"3-7": 2.5},
            "QPL": {"3-7": 1.5, "2-3": 3.0, "2-7": 3.5},
            "EXA": {"3-7": 5.0},
            "TLA": {"2-3-7": 8.0},
            "TRI": {"3-7-2": 20.0},
        },
    )


def test_winning_tickets_from_ordered_triple() -> None:
    won = winning_tickets([(3, 7, 2)])
    assert won["WIN"] == {"3"}
    assert won["PLC"] == {"3", "7", "2"}
    assert won["QNL"] == {"3-7"}
    assert won["QPL"] == {"3-7", "2-3", "2-7"}
    assert won["EXA"] == {"3-7"}
    assert won["TLA"] == {"2-3-7"}
    assert won["TRI"] == {"3-7-2"}


def test_ticket_rule_counts_and_settlement() -> None:
    race = sample_race()
    assert tickets("exa12_rev", race) == ("EXA", ("3-7", "7-3"))
    assert len(tickets("tri123_box", race)[1]) == 6
    assert tickets("tla12_345", race)[1] == ("2-3-7", "3-7-9", "3-5-7")
    result = summary([race], "plc3", 2025)
    assert result["races"] == 1
    assert result["hits"] == 1
    assert result["return_pct"] == 150.0

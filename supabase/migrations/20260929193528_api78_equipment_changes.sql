-- Keep API24's full equipment list untouched. API78 supplies the official
-- abbreviated race-card wording and its explicit new/removed markers.
ALTER TABLE public.race_entries
    ADD COLUMN equipment_card_raw text,
    ADD COLUMN equipment_card_observed_at_ms bigint;

CREATE TABLE public.entry_equipment_changes (
    race_entry_id integer NOT NULL
        REFERENCES public.race_entries(id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position > 0),
    equipment_name_raw text NOT NULL,
    change_type varchar(10) NOT NULL
        CHECK (change_type IN ('added', 'removed')),
    observed_at_ms bigint NOT NULL,
    PRIMARY KEY (race_entry_id, position)
);

ALTER TABLE public.entry_equipment_changes ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON public.entry_equipment_changes
    FROM PUBLIC, anon, authenticated;

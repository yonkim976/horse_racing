alter table public.horses
    add column is_active boolean,
    add column active_status_observed_at_ms bigint,
    add column active_status_source varchar(100);

alter table public.horses
    add constraint ck_horses_active_status_evidence
    check (
        (
            is_active is null
            and active_status_observed_at_ms is null
            and active_status_source is null
        )
        or (
            is_active is not null
            and active_status_observed_at_ms > 0
            and active_status_source is not null
        )
    );

create index ix_horses_is_active on public.horses (is_active);

comment on column public.horses.is_active is
    'Official KRA lifecycle status: true=active, false=inactive, null=not yet verified.';
comment on column public.horses.active_status_observed_at_ms is
    'Unix epoch milliseconds when the official lifecycle status was observed.';
comment on column public.horses.active_status_source is
    'Identifier of the official source used to determine is_active.';

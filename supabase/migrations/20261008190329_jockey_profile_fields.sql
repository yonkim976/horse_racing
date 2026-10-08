alter table public.jockey_affiliation_snapshots
    add column debut_date date,
    add column riding_weight_own_kg numeric(4,1),
    add column riding_weight_other_kg numeric(4,1),
    add constraint jockey_profile_debut_valid check (debut_date >= date '1900-01-01'),
    add constraint jockey_profile_own_weight_valid check (riding_weight_own_kg > 0 and riding_weight_own_kg < 100),
    add constraint jockey_profile_other_weight_valid check (riding_weight_other_kg > 0 and riding_weight_other_kg < 100);

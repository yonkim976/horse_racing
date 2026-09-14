-- SQLite schema snapshot; not PostgreSQL migration SQL.

CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL,
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE entry_equipment (
	id INTEGER NOT NULL,
	horse_id INTEGER,
	meet_code INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER NOT NULL,
	horse_number INTEGER,
	equipment_raw VARCHAR(200),
	bleeding_count INTEGER,
	bleeding_date_raw VARCHAR(40),
	illness_note VARCHAR(200),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_entry_equipment PRIMARY KEY (id),
	CONSTRAINT fk_entry_equipment_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE SET NULL,
	CONSTRAINT uq_entry_equipment_natural UNIQUE (meet_code, race_date_local, race_number, horse_number)
);

CREATE TABLE horse_grade_changes (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER,
	blood_type VARCHAR(50),
	grade_before VARCHAR(30),
	grade_after VARCHAR(30),
	start_date_local DATE,
	end_date_local DATE,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_grade_changes PRIMARY KEY (id),
	CONSTRAINT fk_horse_grade_changes_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_grade_changes_natural UNIQUE (horse_id, start_date_local, grade_before, grade_after)
);

CREATE TABLE horse_medical (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER NOT NULL,
	clinic_date_local DATE NOT NULL,
	stable_part INTEGER,
	hospital_name VARCHAR(100),
	diagnosis_1 VARCHAR(200),
	diagnosis_2 VARCHAR(200),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_medical PRIMARY KEY (id),
	CONSTRAINT fk_horse_medical_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_medical_natural UNIQUE (horse_id, meet_code, clinic_date_local, hospital_name, diagnosis_1, diagnosis_2)
);

CREATE TABLE horse_profile_snapshots (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER,
	grade VARCHAR(30),
	rating FLOAT,
	race_count_total INTEGER,
	race_count_year INTEGER,
	win_count_total INTEGER,
	win_count_year INTEGER,
	second_count_total INTEGER,
	second_count_year INTEGER,
	third_count_total INTEGER,
	third_count_year INTEGER,
	prize_money_total_krw INTEGER,
	last_sale_amount_raw VARCHAR(100),
	trainer_kra_id VARCHAR(30),
	trainer_name VARCHAR(100),
	owner_kra_id VARCHAR(30),
	owner_name VARCHAR(100),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_profile_snapshots PRIMARY KEY (id),
	CONSTRAINT fk_horse_profile_snapshots_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_profile_snapshots_horse_observed UNIQUE (horse_id, observed_at_ms)
);

CREATE TABLE horse_rating_snapshots (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER,
	rating_1 FLOAT,
	rating_2 FLOAT,
	rating_3 FLOAT,
	rating_4 FLOAT,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_rating_snapshots PRIMARY KEY (id),
	CONSTRAINT fk_horse_rating_snapshots_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_rating_snapshots_horse_observed UNIQUE (horse_id, observed_at_ms)
);

CREATE TABLE horse_start_training (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER NOT NULL,
	training_date_local DATE NOT NULL,
	stable_part INTEGER,
	stable_number INTEGER,
	rider_name VARCHAR(100),
	remark VARCHAR(200),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_start_training PRIMARY KEY (id),
	CONSTRAINT fk_horse_start_training_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_start_training_natural UNIQUE (horse_id, meet_code, training_date_local, stable_part, stable_number, rider_name)
);

CREATE TABLE horse_training (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER NOT NULL,
	training_date_local DATE NOT NULL,
	stable_part INTEGER,
	stable_number INTEGER,
	trainer_name VARCHAR(100),
	rider_type VARCHAR(30),
	rider_id VARCHAR(30),
	started_at_raw VARCHAR(20),
	ended_at_raw VARCHAR(20),
	duration_seconds INTEGER,
	canter_count INTEGER,
	gallop_count INTEGER,
	entry_plan VARCHAR(50),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_training PRIMARY KEY (id),
	CONSTRAINT fk_horse_training_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_training_natural UNIQUE (horse_id, meet_code, training_date_local, started_at_raw, ended_at_raw)
);

CREATE TABLE horse_weight_history (
	id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	meet_code INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER,
	horse_number INTEGER,
	body_weight_kg INTEGER,
	body_weight_change_kg INTEGER,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_weight_history PRIMARY KEY (id),
	CONSTRAINT fk_horse_weight_history_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE,
	CONSTRAINT uq_horse_weight_history_natural UNIQUE (horse_id, meet_code, race_date_local, race_number, horse_number)
);

CREATE TABLE horses (
	id INTEGER NOT NULL,
	kra_horse_id VARCHAR(30) NOT NULL,
	name_ko VARCHAR(100) NOT NULL,
	name_en VARCHAR(150),
	sex VARCHAR(20),
	birth_date DATE,
	origin_country VARCHAR(50), grade VARCHAR(30), meet_code INTEGER, sire_kra_id VARCHAR(30), sire_name VARCHAR(100), dam_kra_id VARCHAR(30), dam_name VARCHAR(100), last_sale_amount_raw VARCHAR(100), profile_observed_at_ms BIGINT,
	CONSTRAINT pk_horses PRIMARY KEY (id),
	CONSTRAINT uq_horses_kra_horse_id UNIQUE (kra_horse_id)
);

CREATE TABLE ingestion_runs (
	id INTEGER NOT NULL,
	source VARCHAR(100) NOT NULL,
	data_type VARCHAR(100) NOT NULL,
	started_at_ms BIGINT NOT NULL,
	completed_at_ms BIGINT,
	status VARCHAR(20) NOT NULL,
	records_fetched INTEGER NOT NULL,
	records_written INTEGER NOT NULL,
	error_message TEXT,
	CONSTRAINT pk_ingestion_runs PRIMARY KEY (id),
	CONSTRAINT ck_ingestion_runs_valid_status CHECK (status IN ('running', 'completed', 'failed', 'partial'))
);

CREATE TABLE jockey_changes (
	id INTEGER NOT NULL,
	horse_id INTEGER,
	meet_code INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER NOT NULL,
	horse_number INTEGER NOT NULL,
	jockey_before_id VARCHAR(30),
	jockey_before_name VARCHAR(100),
	jockey_after_id VARCHAR(30),
	jockey_after_name VARCHAR(100),
	carried_weight_before_kg FLOAT,
	carried_weight_after_kg FLOAT,
	reason VARCHAR(200),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_jockey_changes PRIMARY KEY (id),
	CONSTRAINT fk_jockey_changes_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE SET NULL,
	CONSTRAINT uq_jockey_changes_natural UNIQUE (meet_code, race_date_local, race_number, horse_number, jockey_before_id, jockey_after_id)
);

CREATE TABLE jockeys (
	id INTEGER NOT NULL,
	kra_jockey_id VARCHAR(30) NOT NULL,
	name_ko VARCHAR(100) NOT NULL,
	name_en VARCHAR(150),
	CONSTRAINT pk_jockeys PRIMARY KEY (id),
	CONSTRAINT uq_jockeys_kra_jockey_id UNIQUE (kra_jockey_id)
);

CREATE TABLE model_predictions (
	id INTEGER NOT NULL,
	prediction_run_id INTEGER NOT NULL,
	race_id INTEGER NOT NULL,
	race_entry_id INTEGER NOT NULL,
	horse_number INTEGER NOT NULL,
	prob_win FLOAT NOT NULL,
	prob_top2 FLOAT NOT NULL,
	prob_top3 FLOAT NOT NULL,
	CONSTRAINT pk_model_predictions PRIMARY KEY (id),
	CONSTRAINT ck_model_predictions_ck_model_predictions_positive_horse CHECK (horse_number > 0),
	CONSTRAINT ck_model_predictions_ck_model_predictions_win_probability CHECK (prob_win >= 0 AND prob_win <= 1),
	CONSTRAINT ck_model_predictions_ck_model_predictions_top2_probability CHECK (prob_top2 >= 0 AND prob_top2 <= 1),
	CONSTRAINT ck_model_predictions_ck_model_predictions_top3_probability CHECK (prob_top3 >= 0 AND prob_top3 <= 1),
	CONSTRAINT fk_model_predictions_prediction_run_id_prediction_runs FOREIGN KEY(prediction_run_id) REFERENCES prediction_runs (id) ON DELETE RESTRICT,
	CONSTRAINT fk_model_predictions_race_entry_id_race_entries FOREIGN KEY(race_entry_id) REFERENCES race_entries (id) ON DELETE RESTRICT,
	CONSTRAINT fk_model_predictions_race_id_races FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE RESTRICT,
	CONSTRAINT uq_model_predictions_run_entry UNIQUE (prediction_run_id, race_entry_id)
);

CREATE TABLE odds_snapshots (
	id INTEGER NOT NULL,
	race_id INTEGER NOT NULL,
	bet_type VARCHAR(30) NOT NULL,
	selection_key VARCHAR(50) NOT NULL,
	odds FLOAT NOT NULL,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_odds_snapshots PRIMARY KEY (id),
	CONSTRAINT odds_observation UNIQUE (race_id, bet_type, selection_key, observed_at_ms),
	CONSTRAINT ck_odds_snapshots_positive_odds CHECK (odds > 0),
	CONSTRAINT fk_odds_snapshots_race_id_races FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE
);

CREATE TABLE owners (
	id INTEGER NOT NULL,
	kra_owner_id VARCHAR(30) NOT NULL,
	name_ko VARCHAR(100) NOT NULL,
	name_en VARCHAR(150),
	CONSTRAINT pk_owners PRIMARY KEY (id),
	CONSTRAINT uq_owners_kra_owner_id UNIQUE (kra_owner_id)
);

CREATE TABLE prediction_outcomes (
	id INTEGER NOT NULL,
	settlement_id INTEGER NOT NULL,
	model_prediction_id INTEGER NOT NULL,
	finish_position INTEGER,
	is_scored BOOLEAN NOT NULL,
	exclusion_reason VARCHAR(100),
	win BOOLEAN,
	top2 BOOLEAN,
	top3 BOOLEAN,
	win_log_loss FLOAT,
	CONSTRAINT pk_prediction_outcomes PRIMARY KEY (id),
	CONSTRAINT ck_prediction_outcomes_ck_prediction_outcomes_positive_finish CHECK (finish_position IS NULL OR finish_position > 0),
	CONSTRAINT ck_prediction_outcomes_ck_prediction_outcomes_scoring_state CHECK ((is_scored = 1 AND exclusion_reason IS NULL AND win IS NOT NULL AND top2 IS NOT NULL AND top3 IS NOT NULL AND win_log_loss IS NOT NULL) OR (is_scored = 0 AND exclusion_reason IS NOT NULL AND win IS NULL AND top2 IS NULL AND top3 IS NULL AND win_log_loss IS NULL)),
	CONSTRAINT fk_prediction_outcomes_model_prediction_id_model_predictions FOREIGN KEY(model_prediction_id) REFERENCES model_predictions (id) ON DELETE RESTRICT,
	CONSTRAINT fk_prediction_outcomes_settlement_id_prediction_settlements FOREIGN KEY(settlement_id) REFERENCES prediction_settlements (id) ON DELETE RESTRICT,
	CONSTRAINT uq_prediction_outcomes_model_prediction_id UNIQUE (model_prediction_id)
);

CREATE TABLE prediction_runs (
	id INTEGER NOT NULL,
	public_id VARCHAR(36) NOT NULL,
	experiment_run_id VARCHAR(36) NOT NULL,
	model_type VARCHAR(100) NOT NULL,
	dataset_version VARCHAR(100) NOT NULL,
	as_of_policy VARCHAR(50) NOT NULL,
	race_date_local DATE NOT NULL,
	feature_cutoff_at_ms BIGINT NOT NULL,
	published_at_ms BIGINT NOT NULL,
	publication_mode VARCHAR(20) NOT NULL,
	model_artifact_sha256 VARCHAR(64) NOT NULL,
	feature_hash VARCHAR(64) NOT NULL,
	predictions_sha256 VARCHAR(64) NOT NULL,
	notes TEXT,
	CONSTRAINT pk_prediction_runs PRIMARY KEY (id),
	CONSTRAINT ck_prediction_runs_ck_prediction_runs_publication_mode CHECK (publication_mode IN ('live', 'historical')),
	CONSTRAINT ck_prediction_runs_ck_prediction_runs_cutoff_before_publication CHECK (feature_cutoff_at_ms <= published_at_ms),
	CONSTRAINT uq_prediction_runs_predictions_sha256 UNIQUE (predictions_sha256),
	CONSTRAINT uq_prediction_runs_public_id UNIQUE (public_id)
);

CREATE TABLE prediction_settlements (
	id INTEGER NOT NULL,
	public_id VARCHAR(36) NOT NULL,
	prediction_run_id INTEGER NOT NULL,
	settled_at_ms BIGINT NOT NULL,
	outcomes_sha256 VARCHAR(64) NOT NULL,
	n_races INTEGER NOT NULL,
	n_entries INTEGER NOT NULL,
	n_excluded_races INTEGER DEFAULT '0' NOT NULL,
	win_log_loss FLOAT NOT NULL,
	win_brier FLOAT NOT NULL,
	win_ece FLOAT NOT NULL,
	win_top1_hit_rate FLOAT NOT NULL,
	win_top3_inclusion_rate FLOAT NOT NULL,
	top2_log_loss FLOAT NOT NULL,
	top3_log_loss FLOAT NOT NULL,
	CONSTRAINT pk_prediction_settlements PRIMARY KEY (id),
	CONSTRAINT ck_prediction_settlements_ck_prediction_settlements_positive_races CHECK (n_races > 0),
	CONSTRAINT ck_prediction_settlements_ck_prediction_settlements_positive_entries CHECK (n_entries > 0),
	CONSTRAINT ck_prediction_settlements_ck_prediction_settlements_excluded_races CHECK (n_excluded_races >= 0 AND n_excluded_races < n_races),
	CONSTRAINT fk_prediction_settlements_prediction_run_id_prediction_runs FOREIGN KEY(prediction_run_id) REFERENCES prediction_runs (id) ON DELETE RESTRICT,
	CONSTRAINT uq_prediction_settlements_outcomes_sha256 UNIQUE (outcomes_sha256),
	CONSTRAINT uq_prediction_settlements_prediction_run_id UNIQUE (prediction_run_id),
	CONSTRAINT uq_prediction_settlements_public_id UNIQUE (public_id)
);

CREATE TABLE race_entries (
	id INTEGER NOT NULL,
	race_id INTEGER NOT NULL,
	horse_id INTEGER NOT NULL,
	jockey_id INTEGER,
	trainer_id INTEGER,
	owner_id INTEGER,
	horse_number INTEGER NOT NULL,
	gate_number INTEGER,
	carried_weight_kg FLOAT,
	body_weight_kg INTEGER,
	body_weight_change_kg INTEGER,
	rating FLOAT,
	running_style VARCHAR(30),
	scratched BOOLEAN NOT NULL, equipment TEXT,
	CONSTRAINT pk_race_entries PRIMARY KEY (id),
	CONSTRAINT race_horse_number UNIQUE (race_id, horse_number),
	CONSTRAINT race_horse UNIQUE (race_id, horse_id),
	CONSTRAINT ck_race_entries_positive_horse_number CHECK (horse_number > 0),
	CONSTRAINT fk_race_entries_race_id_races FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE,
	CONSTRAINT fk_race_entries_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE RESTRICT,
	CONSTRAINT fk_race_entries_jockey_id_jockeys FOREIGN KEY(jockey_id) REFERENCES jockeys (id),
	CONSTRAINT fk_race_entries_trainer_id_trainers FOREIGN KEY(trainer_id) REFERENCES trainers (id),
	CONSTRAINT fk_race_entries_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
);

CREATE TABLE race_results (
	id INTEGER NOT NULL,
	race_entry_id INTEGER NOT NULL,
	finish_position INTEGER,
	finish_time_ms INTEGER,
	margin_text VARCHAR(50),
	prize_money_krw BIGINT,
	disqualified BOOLEAN NOT NULL, bonus_prize_money_krw BIGINT, rank_remark VARCHAR(200),
	CONSTRAINT pk_race_results PRIMARY KEY (id),
	CONSTRAINT ck_race_results_positive_finish_position CHECK (finish_position IS NULL OR finish_position > 0),
	CONSTRAINT ck_race_results_positive_time CHECK (finish_time_ms IS NULL OR finish_time_ms > 0),
	CONSTRAINT uq_race_results_race_entry_id UNIQUE (race_entry_id),
	CONSTRAINT fk_race_results_race_entry_id_race_entries FOREIGN KEY(race_entry_id) REFERENCES race_entries (id) ON DELETE CASCADE
);

CREATE TABLE race_scratches (
	id INTEGER NOT NULL,
	horse_id INTEGER,
	meet_code INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER NOT NULL,
	horse_number INTEGER,
	reason VARCHAR(200),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_race_scratches PRIMARY KEY (id),
	CONSTRAINT fk_race_scratches_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE SET NULL,
	CONSTRAINT uq_race_scratches_natural UNIQUE (meet_code, race_date_local, race_number, horse_id)
);

CREATE TABLE race_section_results (
	id INTEGER NOT NULL,
	race_entry_id INTEGER NOT NULL,
	section_code VARCHAR(20) NOT NULL,
	distance_from_start_m INTEGER,
	elapsed_time_ms INTEGER,
	position INTEGER,
	gap_to_leader_lengths FLOAT,
	group_notation_raw TEXT, time_basis VARCHAR(20), source_kind VARCHAR(30),
	CONSTRAINT pk_race_section_results PRIMARY KEY (id),
	CONSTRAINT entry_section UNIQUE (race_entry_id, section_code),
	CONSTRAINT ck_race_section_results_nonnegative_distance CHECK (distance_from_start_m IS NULL OR distance_from_start_m >= 0),
	CONSTRAINT ck_race_section_results_positive_position CHECK (position IS NULL OR position > 0),
	CONSTRAINT fk_race_section_results_race_entry_id_race_entries FOREIGN KEY(race_entry_id) REFERENCES race_entries (id) ON DELETE CASCADE
);

CREATE TABLE race_steward_reports (
	id INTEGER NOT NULL,
	meet_code INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER NOT NULL,
	weather VARCHAR(100),
	members TEXT,
	judgement TEXT,
	additional_judgement TEXT,
	jockey_change_note TEXT,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_race_steward_reports PRIMARY KEY (id),
	CONSTRAINT uq_race_steward_reports_natural UNIQUE (meet_code, race_date_local, race_number)
);

CREATE TABLE racecourses (
	id INTEGER NOT NULL,
	kra_meet_code INTEGER NOT NULL,
	code VARCHAR(30) NOT NULL,
	name_ko VARCHAR(50) NOT NULL,
	name_en VARCHAR(100),
	CONSTRAINT pk_racecourses PRIMARY KEY (id),
	CONSTRAINT uq_racecourses_kra_meet_code UNIQUE (kra_meet_code),
	CONSTRAINT uq_racecourses_code UNIQUE (code)
);

CREATE TABLE races (
	id INTEGER NOT NULL,
	racecourse_id INTEGER NOT NULL,
	race_date_local DATE NOT NULL,
	race_number INTEGER NOT NULL,
	distance_m INTEGER NOT NULL,
	grade VARCHAR(50),
	race_name VARCHAR(200),
	scheduled_at_ms BIGINT,
	weather VARCHAR(30),
	track_condition VARCHAR(30),
	track_moisture_percent FLOAT,
	status VARCHAR(20) NOT NULL, race_day_count INTEGER, field_size INTEGER, burden_type VARCHAR(50), age_condition VARCHAR(100), sex_condition VARCHAR(100), rating_condition VARCHAR(100), newcomer_condition VARCHAR(100), actual_start_at_ms BIGINT, start_time_change_reason VARCHAR(300), weather_planned VARCHAR(30), track_condition_planned VARCHAR(30), track_moisture_percent_planned FLOAT,
	CONSTRAINT pk_races PRIMARY KEY (id),
	CONSTRAINT race_identity UNIQUE (racecourse_id, race_date_local, race_number),
	CONSTRAINT ck_races_positive_distance CHECK (distance_m > 0),
	CONSTRAINT ck_races_positive_race_number CHECK (race_number > 0),
	CONSTRAINT fk_races_racecourse_id_racecourses FOREIGN KEY(racecourse_id) REFERENCES racecourses (id) ON DELETE RESTRICT
);

CREATE TABLE running_trial_results (
	id INTEGER NOT NULL,
	running_trial_id INTEGER NOT NULL,
	horse_id INTEGER,
	jockey_id INTEGER,
	trainer_id INTEGER,
	horse_number INTEGER NOT NULL,
	horse_name_raw VARCHAR(100) NOT NULL,
	finish_position INTEGER,
	finish_rank_raw VARCHAR(10),
	origin_country VARCHAR(30),
	sex VARCHAR(20),
	age INTEGER,
	carried_weight_base_kg FLOAT,
	carried_weight_extra_kg FLOAT,
	carried_weight_raw VARCHAR(30),
	jockey_name_raw VARCHAR(100),
	trainer_name_raw VARCHAR(100),
	body_weight_kg INTEGER,
	finish_time_ms INTEGER,
	margin_text VARCHAR(50),
	judgement VARCHAR(20),
	failure_reason VARCHAR(100),
	inspection_reason VARCHAR(150),
	g3f_ms INTEGER,
	s1f_ms INTEGER,
	corner_3_ms INTEGER,
	corner_4_ms INTEGER,
	g1f_ms INTEGER,
	section_400_ms INTEGER,
	final_400_ms INTEGER,
	passing_order_raw VARCHAR(100),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_running_trial_results PRIMARY KEY (id),
	CONSTRAINT ck_running_trial_results_ck_running_trial_results_positive_horse_number CHECK (horse_number > 0),
	CONSTRAINT ck_running_trial_results_ck_running_trial_results_positive_finish_position CHECK (finish_position IS NULL OR finish_position > 0),
	CONSTRAINT fk_running_trial_results_horse_id_horses FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE SET NULL,
	CONSTRAINT fk_running_trial_results_jockey_id_jockeys FOREIGN KEY(jockey_id) REFERENCES jockeys (id) ON DELETE SET NULL,
	CONSTRAINT fk_running_trial_results_running_trial_id_running_trials FOREIGN KEY(running_trial_id) REFERENCES running_trials (id) ON DELETE CASCADE,
	CONSTRAINT fk_running_trial_results_trainer_id_trainers FOREIGN KEY(trainer_id) REFERENCES trainers (id) ON DELETE SET NULL,
	CONSTRAINT uq_running_trial_results_natural UNIQUE (running_trial_id, horse_number)
);

CREATE TABLE running_trials (
	id INTEGER NOT NULL,
	source_document_id INTEGER,
	meet_code INTEGER NOT NULL,
	trial_date_local DATE NOT NULL,
	trial_round INTEGER,
	trial_race_number INTEGER NOT NULL,
	distance_m INTEGER NOT NULL,
	weather VARCHAR(30),
	track_condition VARCHAR(30),
	track_moisture_percent FLOAT,
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_running_trials PRIMARY KEY (id),
	CONSTRAINT ck_running_trials_ck_running_trials_positive_race CHECK (trial_race_number > 0),
	CONSTRAINT ck_running_trials_ck_running_trials_positive_distance CHECK (distance_m > 0),
	CONSTRAINT fk_running_trials_source_document_id_source_documents FOREIGN KEY(source_document_id) REFERENCES source_documents (id) ON DELETE SET NULL,
	CONSTRAINT uq_running_trials_natural UNIQUE (meet_code, trial_date_local, trial_race_number)
);

CREATE TABLE "source_documents" (
	id INTEGER NOT NULL,
	ingestion_run_id INTEGER NOT NULL,
	source_url TEXT NOT NULL,
	retrieved_at_ms BIGINT NOT NULL,
	content_type VARCHAR(100),
	local_path TEXT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	endpoint VARCHAR(200),
	operation VARCHAR(100),
	request_params_json TEXT NOT NULL,
	requested_at_ms BIGINT NOT NULL,
	http_status_code INTEGER,
	response_bytes INTEGER NOT NULL,
	CONSTRAINT pk_source_documents PRIMARY KEY (id),
	CONSTRAINT fk_source_documents_ingestion_run_id_ingestion_runs FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id) ON DELETE CASCADE,
	CONSTRAINT ingestion_run_source_url_sha256 UNIQUE (ingestion_run_id, source_url, sha256)
);

CREATE TABLE trainers (
	id INTEGER NOT NULL,
	kra_trainer_id VARCHAR(30) NOT NULL,
	name_ko VARCHAR(100) NOT NULL,
	name_en VARCHAR(150),
	CONSTRAINT pk_trainers PRIMARY KEY (id),
	CONSTRAINT uq_trainers_kra_trainer_id UNIQUE (kra_trainer_id)
);

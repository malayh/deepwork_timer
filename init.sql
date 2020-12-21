create table tasks(
    t_id integer primary key,
    t_objective text not null,
    t_duration_s text not null,
    t_start_ts integer not null,
    t_end_ts integer
);

create table distractions(
    d_id integer primary key,
    t_id integer not null,
    d_ts integer not null
);

create table pauses(
    p_id integer primary key,
    t_id integer not null,
    p_start_ts integer not null,
    p_end_ts integer not null
);
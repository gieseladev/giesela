create table roles
(
    id          bigserial primary key,
    guild_id    text,
    name        text       not null,
    permissions smallint[] not null
);

create unique index roles_guild_id_name_uindex
    on roles (guild_id, name);

create table role_targets
(
    id      bigserial primary key,
    target  text   not null,
    role_id bigint not null references roles on delete cascade
);
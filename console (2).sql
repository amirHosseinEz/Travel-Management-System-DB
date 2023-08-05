CREATE TABLE IF NOT EXISTS cities
(
    id      serial primary key,
    country text not null,
    city    text not null
);
CREATE TABLE IF NOT EXISTS agencies
(
    id   serial primary key,
    name text
);
CREATE TABLE IF NOT EXISTS travels
(
    id               serial primary key,
    travel_date      timestamp   NOT NULL,
    vehicle_type     VARCHAR(20) NOT NULL,
    price            int         not null,
    number_of_seats  int         not null default 0,
    source_city      int         not null,
    destination_city int         not null,
    agency_id        int         not null,
    constraint positive_price check ( price >= 0 ),
    constraint check_vehicle check ( vehicle_type in ('bus', 'train', 'airplane') ),
    constraint check_source foreign key (source_city) references cities on delete cascade on update cascade,
    constraint check_dest foreign key (destination_city) references cities on delete cascade on update cascade,
    constraint agency_check foreign key (agency_id) references agencies on delete cascade on update cascade,
    constraint check_diff check ( source_city != destination_city )
);



CREATE TABLE IF NOT EXISTS users
(
    id              serial primary key,
    first_name      text        not null,
    last_name       text        not null,
    password        text        not null,
    email           text        not null unique,
    phone_number    varchar(11) not null unique,
    is_active       bool default false,
    user_role       varchar(20),
    agency_id       int,
    otp             text,
    otp_expire_date timestamp,
    constraint phone_number_length_check check (length(phone_number) = 11 and phone_number ~ '^09[0-9]+$'),
    constraint email_check check ( email like '%@%.%'),
    constraint agency_fk foreign key (agency_id) references agencies on delete cascade on update cascade,
    constraint role_enum check ( user_role in ('passenger', 'manager', 'admin')),
    constraint check_agency check ( (agency_id is null and user_role != 'manager') or
                                    (agency_id is not null and user_role = 'manager') )
);


CREATE TABLE IF NOT EXISTS discounts
(
    code          varchar(30) primary key,
    percent       int,
    maximum_limit int,
    constraint check_max check ( maximum_limit >= 0 ),
    constraint check_percent check ( percent > 0 and percent <= 100 )
);

CREATE TABLE IF NOT EXISTS tickets
(
    id            serial primary key,
    user_id       int         not null,
    status        varchar(20) not null,
    travel_id     int         not null,
    rating        int,
    discount_code varchar(30),
    constraint travel_pk foreign key (travel_id) references travels on delete cascade on update cascade,
    constraint user_pk foreign key (user_id) references users on delete cascade on update cascade,
    constraint discount_pk foreign key (discount_code) references discounts on delete set null on update cascade,
    constraint rate_buys check ( (rating is null) or (rating is not null and status = 'paid') ),
    constraint check_status check ( status in ('paid', 'not_paid') ),
    constraint rate_check check ( rating is null or rating between 1 and 5)
);

CREATE FUNCTION check_tickets_violations() RETURNS trigger AS
$check_tickets_violations$
BEGIN
    IF (select number_of_seats FROM travels WHERE id = NEW.travel_id) <=
       (select count(*) from tickets where travel_id = new.travel_id and status = 'paid') THEN
        RAISE EXCEPTION 'travel is full';
    END IF;
    IF new.rating is not null and (select travel_date from travels where new.travel_id = id) > now() THEN
        RAISE EXCEPTION 'you can not rate before travel date';
    end if;
    IF OLD.status = 'paid' AND OLD.discount_code != new.discount_code THEN
        RAISE EXCEPTION 'can not change discount_code after paying';
    end if;

    RETURN NEW;
END;
$check_tickets_violations$ LANGUAGE plpgsql;
CREATE TRIGGER check_remaining_seats
    BEFORE INSERT OR UPDATE
    ON tickets
    FOR ROW
EXECUTE FUNCTION check_tickets_violations();



CREATE TABLE IF NOT EXISTS support_tickets
(
    id           serial primary key,
    title        text not null,
    passenger_id int  not null,
    constraint passenger_pk foreign key (passenger_id) references users on delete cascade on update cascade
);

CREATE TABLE IF NOT EXISTS messages
(
    id           serial primary key,
    sender_id    int       not null,
    support_id   int       not null,
    txt          text      not null,
    is_seen      bool      not null default false,
    message_date timestamp not null default now(),
    constraint admin_pk foreign key (sender_id) references users on delete cascade on update cascade,
    constraint ticket_pk foreign key (support_id) references support_tickets on delete cascade on update cascade
);

CREATE VIEW tickets_with_price AS
SELECT id,
       user_id,
       status,
       travel_id,
       rating,
       discount_code,
       CASE
           WHEN discount_code is null then (select price from travels where id = t.travel_id)
           WHEN (select price from travels where id = t.travel_id) *
                (100 - (select percent from discounts where discount_code = t.discount_code)) / 100 <
                (select price from travels where id = t.travel_id) -
                (select maximum_limit from discounts where discount_code = t.discount_code) then
                       (select price from travels where id = t.travel_id) -
                       (select maximum_limit from discounts where discount_code = t.discount_code)
           ELSE
                           (select price from travels where id = t.travel_id) *
                           (100 - (select percent from discounts where discount_code = t.discount_code)) / 100
           END price
FROM tickets AS t;

CREATE VIEW travels_with_remaining_seats AS
SELECT t.id,
       vehicle_type,
       source_city,
       destination_city,
       t.price,
       number_of_seats,
       travel_date,
       agency_id,
       a.name                                                                                        as agency_name,
       number_of_seats - (select count(*) from tickets where travel_id = t.id and status = 'paid')   as remaining_seats,
       (select SUM(t2.price) from tickets_with_price t2 where travel_id = t.id and status = 'paid')  as saleing,
       (select AVG(t2.rating) from tickets_with_price t2 where travel_id = t.id and status = 'paid') as rating

FROM travels AS t
         join agencies a on a.id = t.agency_id;

CREATE VIEW agencies_with_rating AS
SELECT *, (select AVG(rating) FROM travels_with_remaining_seats WHERE agency_id = a.id) AS rating
FROM agencies a;



INSERT INTO cities(country, city)
values ('iran', 'shiraz'),
       ('iran', 'mashhad'),
       ('iran', 'tehran');

INSERT INTO agencies(name)
values ('test');

INSERT INTO users(first_name, last_name, password, email, phone_number, user_role, is_active, agency_id)
values ('admin', 'admin', md5('admin'), 'admin@admin.com', '09131234567', 'admin', true, null),
       ('passenger', 'passenger', md5('1234'), 'p@p.com', '09132345678', 'passenger', true, null),
       ('manager', 'manager', md5('1234'), 'a@a.com', '09133456789', 'manager', true, 1);

INSERT INTO travels(travel_date, vehicle_type, price, number_of_seats, source_city, destination_city, agency_id)
values ('2024-02-02 17:00:00', 'bus', 10000, 20, 1, 2, 1);

INSERT INTO tickets(user_id, status, travel_id)
values (2, 'not_paid', 1);


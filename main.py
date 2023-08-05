from typing import Union
from enum import Enum
from datetime import datetime
import uvicorn
from sqlalchemy import create_engine, text
from fastapi import FastAPI
import re

from starlette.responses import RedirectResponse

app = FastAPI()
engine = create_engine('postgresql://postgres:123456@localhost/project')
conn = engine.connect()


def get_query(query, **args):
    try:
        if type(query) == str:
            result = conn.execute(text(query), args)
        else:
            result = conn.execute(query, args)

        r = [dict(zip(result.keys(), row)) for row in result.fetchall()]
        return r
    except Exception as e:
        print(str(e))
        conn.rollback()
        return False


def commit_query(query, **args):
    try:
        conn.execute(text(query), args)
        conn.commit()
        return True
    except Exception as e:
        print(str(e))
        conn.rollback()
        return False


class UserRole(str, Enum):
    ADMIN = 'admin'
    PASSENGER = 'passenger'
    MANAGER = 'manager'
    ANY = 'any'


class VehicleType(str, Enum):
    BUS = 'bus'
    TRAIN = 'train'
    AIRPLANE = 'airplane'


class TicketStatus(str, Enum):
    PAID = 'paid'
    NOT_PAID = 'not_paid'


@app.get('/login', tags=["authentication"])
def login(email_phone: str, password: str, role: UserRole = UserRole.ANY):
    s = get_query(
        "SELECT * FROM users WHERE (email =:e or phone_number =:e) and password = md5(:p)"
        " AND ( :r = 'any' OR user_role = :r ) AND is_active = true",
        e=email_phone, p=password, r=role)
    if s:
        return s[0]
    return False


@app.get('/register', tags=["authentication"])
def register(email: str, phone_number: str, first_name: str, last_name, password: str, role: UserRole,
             agency_id: Union[int, None] = None):
    return commit_query(
        'INSERT INTO users(first_name,last_name, password, email, phone_number, user_role,agency_id) '
        'VALUES (:f,:l,md5( :p ),:e,:pn,:ur,:ai)',
        e=email, p=password, f=first_name, l=last_name, pn=phone_number, ur=role, ai=agency_id)


@app.get('/send_otp', tags=["authentication"])
def send_otp(email_phone: str):
    if commit_query(
            "UPDATE users SET "
            "otp = floor(random() * 100000 + 10000)::int,"
            " otp_expire_date = now() + '00:02:00' "
            "where email =:e or phone_number =:e",
            e=email_phone):
        print(get_query(
            "SELECT otp FROM users "
            "where email = :e or phone_number = :e",
            e=email_phone))
        return True
    else:
        return False


@app.get('/otp', tags=["authentication"])
def otp(email_phone: str, code):
    if commit_query(
            "UPDATE users SET is_active=TRUE WHERE otp = :code "
            "and (email = :e or phone_number = :e) and otp_expire_date > now()",
            e=email_phone, code=code):
        return bool(get_query(
            "SELECT 1 FROM users WHERE "
            "otp = :code and otp_expire_date > now() and (email = :e or phone_number = :e ) and is_active = true",
            e=email_phone, code=code))


@app.get('/create_support_ticket', tags=["support system"])
def create_support_ticket(email_phone: str, password: str, title: str):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query("INSERT INTO support_tickets(title, passenger_id)  VALUES (:t,:pid)", t=title, pid=u['id'])
    return "forbidden"


@app.get('/get_support_tickets', tags=["support system"])
def get_support_tickets(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return get_query("SELECT * FROM support_tickets where passenger_id = :u", u=u['id'])
    return "forbidden"


@app.get('/edit_support_ticket', tags=["support system"])
def edit_support_ticket(email_phone: str, password: str, ticket_id: int, title: str):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return get_query(
            "UPDATE support_tickets SET title=:t FROM support_tickets where id= :tid and passenger_id = :u", u=u['id'],
            tid=ticket_id, t=title)
    return "forbidden"


@app.get('/delete_support_ticket', tags=["support system"])
def delete_support_ticket(email_phone: str, password: str, ticket_id: int):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return get_query("DELETE FROM support_tickets where id= :tid and passenger_id = :u", u=u['id'], tid=ticket_id)
    return "forbidden"


@app.get('/get_messages', tags=["support system"])
def get_messages(email_phone, password, ticket_id: int):
    u = login(email_phone, password)
    if u:
        commit_query(
            "UPDATE messages set is_seen = true where support_id = some ("
            "select id from support_tickets where id = :t and "
            ":r != 'passenger' or (:r = 'passenger' and passenger_id = :u)"
            ") and sender_id != :u",
            t=ticket_id, u=u['id'], r=u['user_role'])
        return get_query(
            "SELECT * FROM messages where support_id = some ("
            "select id from support_tickets where id = :t "
            "and :r != 'passenger' or (:r = 'passenger' and passenger_id = :u)"
            ") order by message_date",
            t=ticket_id, u=u['id'], r=u['user_role'])
    return "forbidden"


@app.get('/send_messages', tags=["support system"])
def send_messages(email_phone: str, password: str, ticket_id: int, message: str):
    u = login(email_phone, password)
    if u:
        return commit_query(
            "INSERT INTO messages(sender_id, support_id, txt) "
            "VALUES (:u,("
            "select id from support_tickets where id = :t "
            "and :r != 'passenger' or (:r = 'passenger' and passenger_id = :u)"
            "),:m)",
            u=u['id'], m=message, t=ticket_id, r=u['user_role'])
    return "forbidden"


@app.get('/add_agency', tags=["admin panel", "agency"])
def add_agency(email_phone: str, password: str, name: str):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query(
            "INSERT INTO agencies(name) VALUES (:name)", name=name)
    else:
        return "forbidden"


@app.get('/update_agency', tags=["admin panel", "agency"])
def update_agency(email_phone: str, password: str, agency_id: int, name: str):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query(
            "UPDATE agencies SET name = (:name) where id=:aid", name=name, aid=agency_id)
    else:
        return "forbidden"


@app.get('/get_agency', tags=["admin panel", "agency"])
def get_agency(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return get_query("SELECT * FROM agencies")
    else:
        return "forbidden"


@app.get('/delete_agency', tags=["admin panel", "agency"])
def delete_agency(email_phone: str, password: str, agency_id: int):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return get_query("DELETE FROM agencies WHERE id = :id", id=agency_id)
    else:
        return "forbidden"


@app.get('/add_city', tags=["admin panel", "city"])
def add_city(email_phone: str, password: str, country: str, city: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return commit_query(
            "INSERT INTO cities(country, city) VALUES (:country,:city)",
            country=country, city=city)
    else:
        return "forbidden"


@app.get('/get_cities', tags=["admin panel", "city"])
def get_cities(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query("SELECT * FROM cities")
    else:
        return "forbidden"


@app.get('/update_city', tags=["admin panel", "city"])
def update_city(email_phone: str, password: str, city_id: int, country: str, city: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return commit_query(
            "UPDATE cities SET country = :country, city = :city where id= :id",
            country=country, city=city, id=city_id)
    else:
        return "forbidden"


@app.get('/delete_city', tags=["admin panel", "city"])
def delete_city(email_phone: str, password: str, city_id: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query("DELETE FROM cities where id= :tid", tid=city_id)
    return "forbidden"


@app.get('/add_discount', tags=["admin panel", "discount"])
def add_discount(email_phone: str, password: str, discount_code: str, percent: int, max_limit: int):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query("INSERT INTO discounts(code, percent, maximum_limit) VALUES (:d,:p,:m)",
                            d=discount_code, p=percent, m=max_limit)
    else:
        return "forbidden"


@app.get('/update_discount', tags=["admin panel", "discount"])
def update_discount(email_phone: str, password: str, discount_code: str, percent: int, max_limit: int):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query("UPDATE discounts SET code = :d,percent = :p,maximum_limit = :m where code = :d",
                            d=discount_code, p=percent, m=max_limit)
    else:
        return "forbidden"


@app.get('/get_discounts', tags=["admin panel", "discount"])
def get_discounts(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query("SELECT * FROM discounts")
    else:
        return "forbidden"


@app.get('/delete_discounts', tags=["admin panel", "discount"])
def delete_discounts(email_phone: str, password: str, discount_code: str):
    u = login(email_phone, password, UserRole.ADMIN)
    if u:
        return commit_query("DELETE FROM discounts WHERE code = :d", d=discount_code)
    else:
        return "forbidden"


@app.get('/get_travels', tags=["manager panel"])
def get_travels(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query(
            "SELECT * FROM travels_with_remaining_seats WHERE agency_id = :agency_id", agency_id=u['agency_id'])
    else:
        return "forbidden"


@app.get('/add_travel', tags=["manager panel"])
def add_travel(email_phone: str, password: str, travel_date: datetime, vehicle_type: VehicleType, price: int,
               number_of_seats: int, source_city: int, destination_city: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return commit_query(
            "INSERT INTO travels(travel_date, vehicle_type, price, source_city, "
            "destination_city,agency_id,number_of_seats) "
            "VALUES (:travel_date,:vehicle_type, :price, :source_city, :destination_city,:no_of_seats, "
            "(SELECT agency_id from users where id = :user_id))",
            travel_date=travel_date, vehicle_type=vehicle_type, price=price, source_city=source_city,
            destination_city=destination_city, user_id=u['id'], no_of_seats=number_of_seats)
    else:
        return "forbidden"


@app.get('/edit_travel', tags=["manager panel"])
def edit_travel(email_phone: str, password: str, travel_id: int, travel_date: datetime, vehicle_type: VehicleType,
                price: int, number_of_seats: int,
                source_city: int, destination_city: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return commit_query(
            "UPDATE travels set travel_date = :travel_date, vehicle_type = :vehicle_type,"
            " price= :price,source_city = :source_city, destination_city = :destination_city,"
            " number_of_seats = :no_of_s "
            "WHERE id = :travel_id",
            travel_date=travel_date, vehicle_type=vehicle_type, price=price, source_city=source_city,
            destination_city=destination_city, travel_id=travel_id, no_of_s=number_of_seats)
    else:
        return "forbidden"


@app.get('/delete_travel', tags=["manager panel"])
def delete_travel(email_phone: str, password: str, travel_id: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query("DELETE FROM travels where id= :tid", tid=travel_id)
    return "forbidden"


@app.get('/get_possible_travels_for_passenger', tags=["passenger panel"])
def get_possible_travels_for_passenger(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return get_query(
            "SELECT * FROM travels_with_remaining_seats where remaining_seats != 0 and travel_date > now()")
    else:
        return "forbidden"


@app.get('/get_possible_travels_for_passenger_with_exact_params', tags=["passenger panel"])
def get_possible_travels_for_passenger_with_exact_params(email_phone: str, password: str, destination_city: int,
                                                         source_city: int, travel_date: datetime):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return get_query(
            "SELECT * FROM travels_with_remaining_seats where remaining_seats != 0 and travel_date > now() AND "
            "destination_city = :destination_city AND source_city = :source_city AND "
            "DATE(travel_date) = DATE(:travel_date)",
            destination_city=destination_city, source_city=source_city,
            travel_date=travel_date
        )
    else:
        return "forbidden"


@app.get('/reserve_ticket', tags=["passenger panel"])
def reserve_ticket(email_phone: str, password: str, travel_id: int):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query(
            "INSERT INTO tickets(user_id, status, travel_id) VALUES "
            "(:u, 'not_paid',(select id from travels_with_remaining_seats where id = :t AND remaining_seats >0))",
            u=u['id'], t=travel_id)
    else:
        return "forbidden"


@app.get('/set_discount', tags=["passenger panel"])
def set_discount(email_phone: str, password: str, ticket_id: int, discount_code: str):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query(
            "UPDATE tickets SET discount_code = :dc WHERE id = :tid AND user_id = :u AND status != 'paid'",
            dc=discount_code, tid=ticket_id, u=u['id'])
    else:
        return "forbidden"


@app.get('/pay_ticket', tags=["passenger panel"])
def pay_ticket(email_phone: str, password: str, ticket_id: int):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query(
            "UPDATE tickets SET status = 'paid' WHERE id = :tid AND user_id = :u "
            "and travel_id = all ((select id from travels_with_remaining_seats where id = :t AND remaining_seats >0))",
            tid=ticket_id, u=u['id'])
    else:
        return "forbidden"


@app.get('/rate_ticket', tags=["passenger panel"])
def rate_ticket(email_phone: str, password: str, ticket_id: int, rate: int):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query(
            "UPDATE tickets SET rating = :r WHERE id = :tid AND user_id = :u",
            tid=ticket_id, u=u['id'], r=rate)
    else:
        return "forbidden"


@app.get('/cancel_ticket', tags=["passenger panel"])
def cancel_ticket(email_phone: str, password: str, ticket_id: int):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u:
        return commit_query(
            "DELETE FROM tickets WHERE id = :tid AND user_id = :u",
            tid=ticket_id, u=u['id'])
    else:
        return "forbidden"


@app.get('/top_5_customers', tags=["manager panel"])
def top_5_customers(email_phone: str, password: str, month: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query(
            "WITH visited_city_count(user_id,city,no) as (select user_id,c.city,count(source_city) from tickets as t"
            " join travels t2 on t2.id = t.travel_id join cities c on c.id = t2.destination_city where"
            " t.status = 'paid' AND DATE_PART('MONTH', t2.travel_date) = :m group by user_id,source_city,c.city"
            ")"
            " SELECT u.first_name || ' ' || u.last_name as full_name ,"
            "email, phone_number, SUM(twp.price) as total_price, count(distinct destination_city) as num_of_dest,"
            "(select city from visited_city_count where user_id = u.id order by no desc limit 1) as most_dest_city_name"
            " FROM tickets_with_price as twp"
            " join users u on u.id = twp.user_id"
            " join travels t on twp.travel_id = t.id"
            " WHERE u.user_role = 'passenger' AND twp.status = 'paid' AND DATE_PART('MONTH', t.travel_date) = :m"
            " GROUP BY u.id,email,phone_number,first_name,last_name ORDER BY SUM(twp.price) desc LIMIT 5", m=month)
    else:
        return "forbidden"


@app.get('/filter_tickets', tags=["passenger panel"])
def filter_tickets(
        email_phone: str,
        password: str,
        rating_min: Union[str, None] = None,
        rating_max: Union[str, None] = None,
        price_min: Union[int, None] = None,
        price_max: Union[int, None] = None,
        status: Union[TicketStatus, None] = None,
        travel_id: Union[int, None] = None,
        vehicle_type: Union[VehicleType, None] = None,
        source_city: Union[str, None] = None,
        destination_city: Union[str, None] = None,
        date_min: Union[datetime, None] = None,
        date_max: Union[datetime, None] = None,
        column: str = 'id',
        ascending: bool = True
):
    u = login(email_phone, password, UserRole.PASSENGER)
    if u and re.match('^[\\w_]+$', column):
        t = 'desc'
        if ascending:
            t = 'asc'
        query = f"SELECT t.id, t.status, t.travel_id," \
                f" t.rating, t.discount_code, t.price FROM tickets_with_price as t " \
                f"join travels t2 on t2.id = t.travel_id join cities c2 on c2.id = t2.destination_city " \
                f"join cities c1 on c1.id = t2.source_city " \
                f"WHERE t.user_id = :u"

        if rating_min is not None:
            query = query + " AND t.rating >= :rating_min"
        if rating_max is not None:
            query = query + " AND t.rating >= :rating_max"
        if price_min is not None:
            query = query + " AND t.price >= :price_min"
        if price_max is not None:
            query = query + " AND t.price <= :price_max"
        if status is not None:
            query = query + " AND t.status = :status"
        if travel_id is not None:
            query = query + " AND t.travel_id = :travel_id"
        if vehicle_type is not None:
            query = query + " AND t2.vehicle_type = :vehicle_type"
        if source_city:
            query = query + " AND c1.city like %:source_city%"
        if destination_city:
            query = query + " AND c2.city like %:destination_city%"
        if date_min is not None:
            query = query + " AND t2.travel_date >= :date_min"
        if date_max is not None:
            query = query + " AND t2.travel_date >= :date_max"
        query += f" ORDER BY t.{column} {t}"

        return get_query(query, u=u['id'], rating_min=rating_min, rating_max=rating_max, price_max=price_max,
                         price_min=price_min, vehicle_type=vehicle_type, source_city=source_city, status=status,
                         destination_city=destination_city, date_min=date_min, date_max=date_max, travel_id=travel_id)
    else:
        return "forbidden"


@app.get("/filter_travels", tags=["manager panel"])
def filter_travels(
        rating_min: Union[str, None] = None,
        rating_max: Union[str, None] = None,
        price_min: Union[int, None] = None,
        price_max: Union[int, None] = None,
        vehicle_type: Union[VehicleType, None] = None,
        source_city: Union[str, None] = None,
        destination_city: Union[str, None] = None,
        date_min: Union[datetime, None] = None,
        date_max: Union[datetime, None] = None,
        number_of_seats_max: Union[int, None] = None,
        number_of_seats_min: Union[int, None] = None,
        number_of_remaining_max: Union[int, None] = None,
        number_of_remaining_min: Union[int, None] = None,
        sort_column: str = 'id', ascending: bool = True
):
    if not re.match('^[\\w_]+$', sort_column):
        return False
    t = 'asc'
    if not ascending:
        t = 'desc'
    query = """
        SELECT t.id, t.travel_date, t.vehicle_type, t.price, t.number_of_seats,t.remaining_seats,
            c1.city AS source_city, c2.city AS destination_city, t.agency_name
        FROM travels_with_remaining_seats t
        JOIN cities c1 ON t.source_city = c1.id
        JOIN cities c2 ON t.destination_city = c2.id
        WHERE 1=1 
        """

    # Apply filters
    if rating_min is not None:
        query = query + " AND t.rating >= :rating_min"
    if rating_max is not None:
        query = query + " AND t.rating >= :rating_max"
    if price_min is not None:
        query = query + " AND t.price >= :price_min"
    if price_max is not None:
        query = query + " AND t.price <= :price_max"
    if vehicle_type is not None:
        query = query + " AND t.vehicle_type = :vehicle_type"
    if source_city:
        query = query + " AND c1.city like %:source_city%"
    if destination_city:
        query = query + " AND c2.city like %:destination_city%"
    if date_min is not None:
        query = query + " AND t.travel_date >= :date_min"
    if date_max is not None:
        query = query + " AND t.travel_date >= :date_max"
    if number_of_seats_min is not None:
        query = query + " AND t.number_of_seats >= :number_of_seats_min"
    if number_of_seats_max is not None:
        query = query + " AND t.number_of_seats >= :number_of_seats_max"
    if number_of_remaining_min is not None:
        query = query + " AND t.number_of_remaining >= :number_of_remaining_min"
    if number_of_remaining_max is not None:
        query = query + " AND t.number_of_remaining >= :number_of_seats_max"

    query += f" ORDER BY t.{sort_column} {t}"
    return get_query(query, rating_min=rating_min, rating_max=rating_max, price_max=price_max, price_min=price_min,
                     vehicle_type=vehicle_type, source_city=source_city, destination_city=destination_city,
                     date_min=date_min, date_max=date_max, number_of_seats_min=number_of_seats_min,
                     number_of_seats_max=number_of_seats_max, number_of_remaining_min=number_of_remaining_min,
                     number_of_remaining_max=number_of_remaining_max)


@app.get('/bestselling_travels', tags=["manager panel"])
def bestselling_travels(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query("SELECT * FROM travels_with_remaining_seats ORDER BY saleing desc LIMIT 10")
    else:
        return "forbidden"


@app.get('/highest_rating', tags=["manager panel"])
def highest_rating(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query(
            "SELECT * FROM travels_with_remaining_seats "
            "WHERE agency_id =:ai ORDER BY rating desc LIMIT 10",
            ai=u['agency_id'])
    else:
        return "forbidden"


@app.get('/get_highest_income', tags=["manager panel"])
def get_highest_income(email_phone: str, password: str, year: int):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query(
            "SELECT TO_CHAR(travel_date,'MONTH') as month,SUM(saleing) as total_income FROM travels_with_remaining_seats WHERE date_part('YEAR',travel_date) = :year "
            "AND agency_id = :ai GROUP BY TO_CHAR(travel_date,'MONTH') ORDER BY SUM(saleing) DESC LIMIT 1",
            ai=u['agency_id'], year=year)
    else:
        return "forbidden"


@app.get('/most_popular_destination', tags=["manager panel"])
def most_popular_destination(email_phone: str, password: str):
    u = login(email_phone, password, UserRole.MANAGER)
    if u:
        return get_query("SELECT c.name,COUNT(*) FROM cities c "
                         "JOIN travels t on c.id = t.destination_city "
                         "JOIN tickets t2 on t.id = t2.travel_id"
                         " WHERE t2.status = 'paid' AND t.agency_id = :ai "
                         "GROUP BY c.name ORDER BY count(*) desc LIMIT 10",
                         ai=u['agency_id'])
    else:
        return "forbidden"


@app.get('/')
def h():
    return RedirectResponse('/docs')


uvicorn.run(app, host="127.0.0.1", port=8080)

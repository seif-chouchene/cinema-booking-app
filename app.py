import os
import psycopg
from dotenv import load_dotenv
from flask import Flask,render_template,redirect,request,session
from psycopg.rows import dict_row

from flask_session import Session;

from werkzeug.security import generate_password_hash,check_password_hash

from functools import wraps

load_dotenv()


app=Flask(__name__)


pwd=os.environ["DB_PASSWORD"]

conn=psycopg.connect(f"dbname=cinema user=postgres password={pwd}",row_factory=dict_row)

cur=conn.cursor()

app.config["SESSION_PERMANENT"]=False
app.config["SESSION_TYPE"]="filesystem"

Session(app)

@app.route("/")
def index():
    cur.execute("select * from movies")
    movies=cur.fetchall()
    return render_template("index.html",movies=movies)


@app.route("/register",methods=["GET","POST"])

def register():
    if request.method=="GET":
        return render_template("register.html")
    if request.method=="POST":
        first_name=request.form.get("first_name")
        last_name=request.form.get("last_name")
        email=(request.form.get("email") or "").strip().lower()
        password=request.form.get("password")
        confirm=request.form.get("confirm_password")
        fields={"first name":first_name,"last name":last_name,"email":email,"password":password}
        for name,value in fields.items():
            if not value:
                return render_template("error.html",message=f"missing {name}")
        if password!=confirm or len(password)<8:
            return render_template("error.html",message="password not matched and be at least 8 C")

        cur.execute("select id from customers where email = %s", (email,))
        if cur.fetchone():
            return render_template("error.html", message="email already used")        
        
        hashed=generate_password_hash(password)
        try:
            cur.execute("insert into customers (name,email,password_hash) values (%s,%s,%s)",(first_name + " " + last_name,email,hashed,))
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(e)
            return render_template("error.html",message="could not create the acc")  
        return render_template("success.html")           
        

@app.route("/login",methods=["GET","POST"])

def login():
    if request.method=="GET":
        return render_template("login.html")
    email=(request.form.get("email") or "").strip().lower()
    password=request.form.get("password") or ""
    cur.execute("select * from customers where email=%s",(email,))
    customer=cur.fetchone()

    if not customer or not customer["password_hash"] or not check_password_hash(customer["password_hash"],password):
        return render_template("error.html",message="email or password invalid")
    session["customer_id"]=customer["id"]
    return redirect("/")

def login_requiered(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "customer_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper

@app.route("/registrants")
@login_requiered
def registrants():
    cur.execute("select b.id,c.name,m.title,r.room_number,b.seats,s.show_date,s.show_time,b.seats*s.price as total,coalesce ((select p.status from payments as p where p.booking_id=b.id),'unpaid') as status from customers as c,movies as m,rooms as r,showtimes as s,bookings as b where c.id=b.customer_id and s.id=b.showtime_id and m.id=s.movie_id and r.id=s.room_id  and b.customer_id=%s order by s.show_date,show_time",(session["customer_id"],))
    bookings=cur.fetchall()
    print(bookings)
    return render_template("registrants.html",bookings=bookings) 

@app.route("/search",methods=["POST"])
@login_requiered
def search():
    q=(request.form.get("q") or "").strip().lower()
    cur.execute("select s.id,m.title,s.show_date,s.show_time,r.room_number,s.price from movies as m ,showtimes as s,rooms as r  where r.id=s.room_id and m.id=s.movie_id and m.title ilike %s order by m.title,s.show_date,s.show_time",("%" + q + "%",))
    showtimes=cur.fetchall()
    return render_template("search.html",showtimes=showtimes)
    


@app.route("/book",methods=["POST"])
@login_requiered
def book():
    showtime_id=request.form.get("showtime_id")
    seats=request.form.get("seats","")
    if not showtime_id or not seats.isdigit() or  not (1<=int(seats)<=10):
        return render_template("error.html",message="showtime_id or seats is invalid")

    try:
        cur.execute("insert into bookings (customer_id,showtime_id,seats) values (%s,%s,%s)",(session["customer_id"],showtime_id,seats,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        return render_template("error.html",message="could not book")
    return redirect("/registrants")

@app.route("/deregister",methods=["POST"])
@login_requiered
def deregister():
    id=request.form.get("id")
    try:
        cur.execute("delete from bookings where id=%s and customer_id =%s",(id,session["customer_id"],))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        return render_template("error.html",message="couldnt delete")
    return redirect("/registrants")


@app.route("/edit")
@login_requiered
def edit():
    booking_id=request.args.get("booking_id","")
    if not booking_id.isdigit():
        return render_template("error.html",message="invalid booking")
    cur.execute("select id,seats from bookings where id=%s and customer_id=%s",(booking_id,session["customer_id"],))
    booking=cur.fetchone()
    if not booking:
        return render_template("error.html",message="booking not found")
    return render_template("edit.html",booking=booking)



@app.route("/update",methods=["POST"])
@login_requiered
def update():
    id=request.form.get("booking_id")
    seats=request.form.get("seats","")
    if not seats.isdigit() or not 1<=int(seats)<=10:
        return render_template("error.html",message="seats invalid")
    try:
        cur.execute("update  bookings set seats=%s where id=%s and customer_id =%s",(seats,id,session["customer_id"]))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        return render_template("error.html",message="couldnt set up anything")
    return redirect("/registrants")








@app.route("/payments",methods=["GET","POST"])
@login_requiered
def payments():
    if request.method=="GET":
        booking_id=request.args.get("booking_id","")
    else:
        booking_id=request.form.get("booking_id","")
    if not booking_id.isdigit():
        return render_template("error.html",message="invalid booking")

    cur.execute("select b.id ,b.seats*s.price as total, coalesce((select p.status from payments as p where p.booking_id=b.id),'unpaid') as status from bookings as b ,showtimes as s where s.id=b.showtime_id  and b.id=%s and b.customer_id=%s",(booking_id,session["customer_id"]))
    booking=cur.fetchone()
    if not booking:
        return render_template("error.html",message="booking not found")
    if booking["status"]=="paid":
        return render_template("error.html",message="already paid")
    if request.method=="GET":
        return render_template("payments.html",booking=booking)
    card_number=request.form.get("card_number","").replace(" ","")
    if not card_number.isdigit() or len(card_number)<13:
        return render_template("error.html",message="invalid card number")
    try:
        cur.execute("insert into payments (booking_id,amount,card_last4) values(%s,%s,%s)",(booking["id"],booking["total"],card_number[-4:]))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        return render_template("error.html",message="already paid or payment failes")
    return redirect("/registrants")
    





@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")






if __name__=="__main__":
    app.run(debug=True)
import os
import numpy as np
import sqlite3

from datetime import datetime
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, draw_chart, is_valid_month, is_valid_username, login_required, swap
from helpers_data import get_data, get_data_locations
from helpers_maps import draw_multi_maps

SHAPE = (91, 91)
DATA_TYPES = ["temp_mean", "temp_max", "temp_min", "precip"]
START = "1950-01"
END = "2023-12"

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response



@app.route("/")
def index():
    message = request.args.get("message")
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    return render_template("index.html", message=message, imgname=imgname)


@app.route("/locations")
def locations():
    strlat = request.args.get("latitude")
    strlon = request.args.get("longitude")
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    if not (strlat and strlon):
        return render_template("locations.html", imgname=imgname)
    try:
        lat = float(strlat)
        lon = float(strlon)
    except:
        return apology("Invalid latitude/longitude", 400)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        print(f"Latitude: {lat} \nLongitude: {lon}")
        return apology(f"Latitude/logitude out of range", 400)
    
    strlat = "{:.2f}".format(lat)
    strlon = "{:.2f}".format(lon)
    filename = "location_data/"+strlat+"_"+strlon+".html"
    if not os.path.isfile("static/"+filename):
        data = get_data(location=(lat, lon), date_end=datetime.today().strftime("%Y-%m-%d"), 
                meteo_types=["temperature_2m_mean", "precipitation_sum"], return_DataFrame=True)
        draw_chart(lat, lon, data, filename=filename.split("/")[1])
    return render_template("locations.html", imgname=imgname, lat=lat, lon=lon, filename=filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    # Forget any user_id
    session.clear()
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        con = sqlite3.connect("static/users.db")
        rows = con.execute(
            "SELECT * FROM users WHERE username = ?", (request.form.get("username"),)
        ).fetchall()

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0][2], request.form.get("password")
        ):
            return apology("invalid username and/or password", 400)

        # Remember which user has logged in
        session["user_id"] = rows[0][0]

        try:
            imgname = con.execute("SELECT img FROM profiles WHERE user_id = ?",
                                 (session["user_id"],)).fetchone()
            print (imgname)
            session["imgname"] = imgname[0]
        except:
            session["imgname"] = None

        # Redirect user to home page
        path = "/?message=Hi!+"+request.form.get("username")
        con.close()
        return redirect(path)

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""
    # Forget any user_id
    session.clear()
    # Redirect user to login form
    return redirect("/")


@app.route("/maps")
def maps():
    month = request.args.get("month-picker")
    data_type = request.args.get("data-type")
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    if not (month and data_type):
        return render_template("maps.html", imgname=imgname, data_types=DATA_TYPES,
                               start=START, end=END)
    elif not is_valid_month(month, start=START, end=END):
        return apology("Invalid month", 400)
    elif data_type not in DATA_TYPES:
        return apology(f"This data type ({data_type}) is not supported", 400)
    else:
        filename = "weather_data/"+month+"_"+data_type+".html"
        if not os.path.isfile("static/"+filename):
            draw_multi_maps(month+"-01", month+"-01", data_type) 
        return render_template("maps.html", imgname=imgname, data_types=DATA_TYPES, 
                               data_type=data_type, month=month,
                               filename=filename, start=START, end=END)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    if request.method == "POST":
        img = request.files.get("img")
        bio = request.form.get("bio")
        
        con = sqlite3.connect("static/users.db")
        if img:
            # Save image only
            try:
                extenstion = os.path.splitext(img.filename)[-1]
                imgname = str(session["user_id"]) + extenstion
                img.save("static/user_img/" + imgname)
                img.close()
            except:
                img.close()
                return apology("Cannot save the image", 400)
            
            # Save its path in database
            try:
                con.execute("UPDATE profiles SET img = ? WHERE user_id = ?",
                           (imgname, session["user_id"]))
                con.commit()
                session["imgname"] = imgname
            except:
                try:
                    con.execute("INSERT INTO profiles (user_id, img) VALUES (?, ?)",
                               (session["user_id"], imgname))
                    con.commit()
                    session["imgname"] = imgname
                except:
                    con.close()
                    return apology("Oh no! Something went wrong",400)
        elif bio:
            # Change bio only
            try:
                con.execute("UPDATE profiles SET bio = ? WHERE user_id = ?", (bio, session["user_id"]))
                con.commit()
            except:
                try:
                    con.execute("INSERT INTO profiles (user_id, bio) VALUES (?, ?)",
                               (session["user_id"], bio))
                    con.commit()
                except:
                    con.close()
                    return apology("Oh no! Something went wrong",400)
        else:
            # Change nothing
            con.close()
            return redirect("/profile?message=Nothing changed")
        con.close()
        return redirect("/profile?message=Succeeded!")

    # If request.method = "GET"
    else:
        con = sqlite3.connect("static/users.db")
        try:
            profile = con.execute("SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
        except:
            con.execute("INSERT INTO profiles (user_id) VALUES (?)", (session["user_id"],))
            con.commit()
            profile = con.execute("SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
        username = con.execute("SELECT username FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        message = request.args.get("message")
        con.close()
        return render_template("profile.html", message=message, username=username[0], bio=profile[1], 
                               imgname=imgname)


@app.route("/references")
def references():
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    return render_template("references.html", imgname=imgname)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        pwd = request.form.get("password")
        re_pwd = request.form.get("confirmation")
        if not username:
            return apology("Username is required", 400)
        if not pwd:
            return apology("Password is required", 400)
        if not re_pwd:
            return apology("Please re-enter the password", 400)
        if not re_pwd == pwd:
            return apology("Re-entered password is inconsistent with password", 400)
        if not is_valid_username(username):
            return apology("Username must be 3-12 characters long and contain only alphanumeric, underscores, or hyphens", 400)
        hash_pwd = generate_password_hash(pwd)
        
        con = sqlite3.connect("static/users.db")
        try:
            con.execute("INSERT INTO users (username, hash_pwd) VALUES (?, ?)", (username, hash_pwd))
            con.commit()
            # Create a profile for the user
            user_id = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            con.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id[0],))
            con.commit()
        except:
            con.close()
            return apology("Username already exists!", 400)
        con.close()
        return render_template("/login.html", username=username)
    else:
        return render_template("/register.html")
    
    
@app.route("/update", methods=["GET", "POST"])
@login_required
def update():
    try:
        imgname = session["imgname"]
    except:
        imgname = None
    if request.method == "POST":
        lat_start = request.form.get("lat_start")
        lat_end = request.form.get("lat_end")
        n_lat = request.form.get("n_lat")
        lon_start = request.form.get("lon_start")
        lon_end = request.form.get("lon_end")
        n_lon = request.form.get("n_lon")
        date_start = request.form.get("date_start")
        date_end = request.form.get("date_end")
        force_update = request.form.get("force_update")
        if not (lat_start and lat_end and n_lat and lon_start and lon_end and n_lon and date_start and date_end):
            return apology("Missing parameter(s)", 400)
        try: 
            lat_start = float(lat_start)
            lat_end = float(lat_end)
            n_lat = int(n_lat)
            lon_start = float(lon_start)
            lon_end = float(lon_end)
            n_lon = int(n_lon)
            dt_date_start = datetime.strptime(date_start,"%Y-%m-%d")
            dt_date_end = datetime.strptime(date_end,"%Y-%m-%d")
        except:
            return apology("Invalid parameter(s)", 400)
        
        # Check if the user is allowed to update database
        if not "user_id" in session:
            return apology("You are not logged in", 400)
        con = sqlite3.connect("static/users.db")
        try:
            is_admin = con.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()[0]
            if not is_admin:
                con.close()
                return apology("Sorry, you are not administrator", 400)
        except:
            con.close()
            return apology("Failed to connect to database", 400)
        con.close()
        
        if force_update:
            print("Force update")
            force_update = True
        else:
            print("No force update")
            force_update = False
        if lat_start > lat_end:
            lat_start, lat_end = swap(lat_start, lat_end)
        if lon_start > lon_end:
            lon_start, lon_end = swap(lon_start, lon_end)
        if dt_date_start > dt_date_end:
            date_start, date_end = swap(date_start, date_end)
        lats = np.linspace(lat_start, lat_end, n_lat)
        lons = np.linspace(lon_start, lon_end, n_lon)
        is_successful = get_data_locations(lats=lats, lons=lons, date_start=date_start, date_end=date_end, 
                           dbpath="static/weather_update.db", force_update_database=force_update)
        if not is_successful:
            return apology("Failed to update data", 400)
        return redirect("/update?message=Succeeded!")
    else:
        message = request.args.get("message")
        start = START + "-01"  # "1950-01-01"
        end = datetime.today().strftime("%Y-%m-%d")  # eg: "2024-12-25"
        return render_template("update.html", message=message, imgname=imgname, 
                               start=start, end=end)
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from dbfunc import getConnection
import hashlib

app = Flask(__name__)
app.secret_key = 'your_secret_key'

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()

        conn = getConnection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)", (full_name, email, hashed_pw))
            conn.commit()
            flash("✅ Registration successful! Please login.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            print("Registration Error:", e)
            flash("❌ Registration failed.", "danger")
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()

        conn = getConnection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user and hashed_pw == user['password']:
            session['user_id'] = user['id']
            session['user_name'] = user['full_name']
            session['is_admin'] = bool(user.get('is_admin', False))
            flash("✅ Logged in successfully!", "success")
            return redirect(url_for('admin_dashboard') if session['is_admin'] else url_for('dashboard'))
        else:
            flash("❌ Incorrect email or password.", "danger")

        cursor.close()
        conn.close()

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect(url_for('login'))
    return render_template('dashboard.html', name=session.get('user_name'))

@app.route('/destinations')
def destinations():
    return render_template('destinations.html')

@app.route('/search')
def search():
    conn = getConnection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT r.airport, r.destination FROM routes r")
    routes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('search.html', routes=routes)

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("❌ Unauthorized access.", "danger")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Metrics
        cursor.execute("SELECT COUNT(*) AS count FROM user_flight")
        total_bookings = cursor.fetchone()['count']

        cursor.execute("SELECT SUM(total_price) AS revenue FROM user_flight")
        total_revenue = cursor.fetchone()['revenue'] or 0

        cursor.execute("""
            SELECT r.airport, r.destination, COUNT(*) AS total
            FROM user_flight uf
            JOIN times t ON uf.flight_id = t.flight_id
            JOIN routes r ON t.flight_route_id = r.route_id
            GROUP BY r.airport, r.destination
            ORDER BY total DESC
            LIMIT 1
        """)
        top = cursor.fetchone()
        top_route = f"{top['airport']} → {top['destination']}" if top else "N/A"

        cursor.execute("SELECT COUNT(DISTINCT user_id) AS count FROM user_flight")
        active_users = cursor.fetchone()['count']

        metrics = {
            'total_bookings': total_bookings,
            'total_revenue': total_revenue,
            'top_route': top_route,
            'active_users': active_users
        }

        # All bookings with ID included
        cursor.execute("""
            SELECT uf.id AS id, u.full_name, uf.booking_date, uf.class, uf.seats, uf.total_price,
                   r.airport, r.destination, t.flight_date
            FROM user_flight uf
            JOIN users u ON uf.user_id = u.id
            JOIN times t ON uf.flight_id = t.flight_id
            JOIN routes r ON t.flight_route_id = r.route_id
            ORDER BY t.flight_date DESC
        """)
        bookings = cursor.fetchall()

    except Exception as e:
        print("Admin dashboard error:", e)
        metrics = {
            'total_bookings': 0,
            'total_revenue': 0,
            'top_route': "Error",
            'active_users': 0
        }
        bookings = []

    finally:
        cursor.close()
        conn.close()

    return render_template('admin_dashboard.html', metrics=metrics, bookings=bookings)

@app.route('/admin/deletebooking/<int:booking_id>')
def delete_booking_admin(booking_id):
    if 'user_id' not in session or not session.get('is_admin'):
        flash("❌ Unauthorized access.", "danger")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_flight WHERE id = %s", (booking_id,))
        conn.commit()
        flash("✅ Booking deleted successfully.", "success")
    except Exception as e:
        print("Admin Delete Error:", e)
        flash("❌ Could not delete booking.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/searchresults')
def searchresults():
    route = request.args.get('route')

    if not route or '-' not in route:
        flash("❌ Invalid route format.", "danger")
        return redirect(url_for('search'))

    airport, destination = route.split('-')
    airport, destination = airport.strip(), destination.strip()

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    # Step 1: Get route ID
    cursor.execute("SELECT route_id FROM routes WHERE airport = %s AND destination = %s", (airport, destination))
    route_row = cursor.fetchone()

    if not route_row:
        flash("❌ No route found.", "danger")
        return redirect(url_for('search'))

    route_id = route_row['route_id']

    cursor.execute("""
        SELECT t.flight_date, t.flight_departure, t.flight_arrival
        FROM times t
        WHERE t.flight_route_id = %s
    """, (route_id,))
    times = cursor.fetchall()

    cursor.execute("SELECT class, fare FROM airfare WHERE route_id = %s", (route_id,))
    fares = cursor.fetchall()

    cursor.close()
    conn.close()

    if not times:
        flash("❌ No flight times found.", "danger")
        return redirect(url_for('search'))

    return render_template('searchresults.html', route=route, times=times, fares=fares)

@app.route('/booking', methods=['GET', 'POST'])
def booking():
    if 'user_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        try:
            route_str = request.form['route']
            booking_date = request.form['booking_date']
            seats = int(request.form['seats'])
            travel_class = request.form['class']
            total_price = float(request.form['total_price'])

            airport, destination = route_str.split('-')

            cursor.execute("""
                SELECT t.flight_id, t.flight_date, t.flight_departure 
                FROM routes r
                JOIN times t ON r.route_id = t.flight_route_id
                WHERE r.airport = %s AND r.destination = %s
                LIMIT 1
            """, (airport.strip(), destination.strip()))

            flight = cursor.fetchone()
            if not flight:
                flash("❌ No matching flight found.", "danger")
                return redirect(url_for('booking'))

            flight_id = flight['flight_id']
            flight_date = flight['flight_date']
            departure_time = flight['flight_departure']

            cursor.execute("""
                INSERT INTO user_flight (user_id, flight_id, booking_date, seats, class, total_price)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session['user_id'], flight_id, booking_date, seats, travel_class, total_price))

            conn.commit()

            return render_template('confirmation.html', booking={
                'origin': airport,
                'destination': destination,
                'class': travel_class,
                'seats': seats,
                'booking_date': booking_date,
                'total_price': total_price,
                'flight_date': flight_date,
                'departure_time': departure_time
            })
        except Exception as e:
            print("Booking Error:", e)
            flash("❌ Booking failed. Please try again.", "danger")
        finally:
            cursor.close()
            conn.close()

    return render_template('booking.html')


@app.route('/mybookings')
def mybookings():
    if 'user_id' not in session:
        flash("⚠️ Please login to view your bookings.", "warning")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT uf.id, uf.booking_date, f.flight_date, f.flight_departure, 
                   r.airport AS origin, r.destination,
                   uf.class, uf.seats, uf.total_price
            FROM user_flight uf
            JOIN times f ON uf.flight_id = f.flight_id
            JOIN routes r ON f.flight_route_id = r.route_id
            WHERE uf.user_id = %s
            ORDER BY f.flight_date DESC
        """, (session['user_id'],))
        bookings = cursor.fetchall()
    except Exception as e:
        print("MyBookings Error:", e)
        bookings = []
        flash("❌ Could not load your bookings.", "danger")
    finally:
        cursor.close()
        conn.close()

    return render_template('mybookings.html', bookings=bookings)


@app.route('/editbooking/<int:booking_id>', methods=['GET', 'POST'])
def editbooking(booking_id):
    if 'user_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        booking_date = request.form['booking_date']
        seats = int(request.form['seats'])
        travel_class = request.form['class']

        cursor.execute("SELECT flight_id FROM user_flight WHERE id = %s AND user_id = %s", (booking_id, session['user_id']))
        booking = cursor.fetchone()
        if not booking:
            flash("❌ Booking not found.", "danger")
            return redirect(url_for('mybookings'))

        flight_id = booking['flight_id']
        cursor.execute("""
            SELECT fare FROM airfare 
            JOIN routes r ON airfare.route_id = r.route_id
            JOIN times t ON r.route_id = t.flight_route_id
            WHERE t.flight_id = %s
            LIMIT 1
        """, (flight_id,))
        fare = cursor.fetchone()
        if not fare:
            flash("❌ Fare not found.", "danger")
            return redirect(url_for('mybookings'))

        base_fare = float(fare['fare'])
        multiplier = {'Economy': 1.0, 'Business': 1.5, 'First': 2.0}.get(travel_class, 1.0)
        total_price = base_fare * multiplier * seats

        cursor.execute("""
            UPDATE user_flight 
            SET booking_date = %s, seats = %s, class = %s, total_price = %s 
            WHERE id = %s AND user_id = %s
        """, (booking_date, seats, travel_class, total_price, booking_id, session['user_id']))

        conn.commit()
        flash("✅ Booking updated successfully!", "success")
        return redirect(url_for('mybookings'))

    cursor.execute("""
        SELECT b.*, r.airport AS origin, r.destination
        FROM user_flight b
        JOIN times t ON b.flight_id = t.flight_id
        JOIN routes r ON t.flight_route_id = r.route_id
        WHERE b.id = %s AND b.user_id = %s
    """, (booking_id, session['user_id']))
    booking = cursor.fetchone()
    cursor.close()
    conn.close()

    if not booking:
        flash("❌ Booking not found.", "danger")
        return redirect(url_for('mybookings'))

    return render_template('editbooking.html', booking=booking)

@app.route('/cancelbooking/<int:booking_id>')
def cancelbooking(booking_id):
    if 'user_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_flight WHERE id = %s AND user_id = %s", (booking_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    flash("✅ Booking canceled successfully.", "success")
    return redirect(url_for('mybookings'))

@app.route('/downloadreceipt/<int:booking_id>')
def downloadreceipt(booking_id):
    if 'user_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.id, b.booking_date, b.seats, b.class, b.total_price,
               r.airport AS origin, r.destination, t.flight_date, t.flight_departure
        FROM user_flight b
        JOIN times t ON b.flight_id = t.flight_id
        JOIN routes r ON t.flight_route_id = r.route_id
        WHERE b.id = %s AND b.user_id = %s
    """, (booking_id, session['user_id']))
    booking = cursor.fetchone()
    cursor.close()
    conn.close()

    if not booking:
        flash("❌ Booking not found.", "danger")
        return redirect(url_for('mybookings'))

    receipt = f"""
        Horizon Travels - Booking Receipt

        Booking ID: {booking['id']}
        Route: {booking['origin']} → {booking['destination']}
        Flight Date: {booking['flight_date']}
        Departure Time: {booking['flight_departure']}
        Travel Class: {booking['class']}
        Seats Booked: {booking['seats']}
        Booking Date: {booking['booking_date']}
        Total Price: £{booking['total_price']}

        Thank you for choosing Horizon Travels!
    """
    return Response(receipt, mimetype='text/plain', headers={"Content-Disposition": f"attachment; filename=receipt_{booking_id}.txt"})

@app.route('/logout')
def logout():
    session.clear()
    flash("✅ Logged out successfully.", "success")
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        flash("⚠️ Please login to change your password.", "warning")
        return redirect(url_for('login'))

    if request.method == 'POST':
        old = request.form['old_password']
        new = request.form['new_password']
        confirm = request.form['confirm_password']

        hashed_old = hashlib.sha256(old.encode()).hexdigest()
        hashed_new = hashlib.sha256(new.encode()).hexdigest()

        conn = getConnection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()

        if not user or user['password'] != hashed_old:
            flash("❌ Current password is incorrect.", "danger")
        elif new != confirm:
            flash("❌ New passwords do not match.", "danger")
        else:
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_new, session['user_id']))
            conn.commit()
            flash("✅ Password updated successfully.", "success")

        cursor.close()
        conn.close()

    return render_template('change_password.html')

@app.route('/admin/change_password', methods=['GET', 'POST'])
def admin_change_password():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("❌ Unauthorized access.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        old = request.form['old_password']
        new = request.form['new_password']
        confirm = request.form['confirm_password']

        hashed_old = hashlib.sha256(old.encode()).hexdigest()
        hashed_new = hashlib.sha256(new.encode()).hexdigest()

        conn = getConnection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()

        if not user or user['password'] != hashed_old:
            flash("❌ Current password is incorrect.", "danger")
        elif new != confirm:
            flash("❌ New passwords do not match.", "danger")
        else:
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_new, session['user_id']))
            conn.commit()
            flash("✅ Password updated successfully.", "success")

        cursor.close()
        conn.close()

    return render_template('admin_change_password.html')

@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("❌ Unauthorized access.", "danger")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Monthly sales: month, total bookings, total revenue
        cursor.execute("""
            SELECT 
                DATE_FORMAT(booking_date, '%%Y-%%m') AS month,
                COUNT(*) AS total_bookings,
                SUM(total_price) AS total_revenue
            FROM user_flight
            GROUP BY month
            ORDER BY month DESC
        """)
        monthly_sales = cursor.fetchall()

        # Top customers: user full name, total bookings, total spent
        cursor.execute("""
            SELECT u.full_name, COUNT(*) AS bookings, SUM(uf.total_price) AS spent
            FROM user_flight uf
            JOIN users u ON uf.user_id = u.id
            GROUP BY uf.user_id
            ORDER BY bookings DESC
            LIMIT 5
        """)
        top_customers = cursor.fetchall()

    except Exception as e:
        print("Report Error:", e)
        monthly_sales = []
        top_customers = []
        flash("❌ Failed to generate reports.", "danger")

    finally:
        cursor.close()
        conn.close()

    return render_template('admin_reports.html', monthly_sales=monthly_sales, top_customers=top_customers)
@app.route('/admin_manage_journeys')
def admin_manage_journeys():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("❌ Unauthorized access.", "danger")
        return redirect(url_for('login'))

    conn = getConnection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM routes")
    routes = cursor.fetchall()

    cursor.execute("SELECT * FROM airfare")
    fares = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin_manage_journeys.html', routes=routes, fares=fares)

if __name__ == '__main__':
    app.run(debug=True)

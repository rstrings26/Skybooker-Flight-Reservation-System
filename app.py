from flask import Flask, render_template, request, redirect, url_for, flash, session, g # type: ignore
from functools import wraps
from db_connection import get_db_connection
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for session management and flash messages

# Global flag to clear session on app start
session_cleared = False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def before_request():
    global session_cleared
    g.user = None

    if not session_cleared:
        session.clear()
        session_cleared = True

    if 'username' in session:
        g.user = session['username']

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

# Route for login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        connection = get_db_connection()
        cursor = connection.cursor()

        # Check if the username and password match
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if user:
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')  # This will show on the login page

    return render_template('login.html')

# Route for signup page
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        connection = get_db_connection() 
        cursor = connection.cursor()

        # Check if the username already exists
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()

        if existing_user:
            flash('Username already exists', 'danger')
        else:
            # Insert the new user into the database
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
            connection.commit()
            flash('Signup successful! Please log in.', 'success')
            return redirect(url_for('login'))

        cursor.close()
        connection.close()

    return render_template('signup.html')

# Route for the homepage
@app.route('/home')
@login_required
def home():
    return render_template('homepage.html')

# Route for the search page
@app.route('/search', methods=['GET', 'POST'])
@login_required
def search_flights():
    if request.method == 'POST':
        source = request.form.get('source')
        destination = request.form.get('destination')
        departure_date = request.form.get('departure_date')

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)  # Use dictionary=True for easier access to column names

        # Query flights from the database
        cursor.execute(
            "SELECT * FROM flights WHERE source = %s AND destination = %s AND departure_date = %s",
            (source, destination, departure_date)
        )
        filtered_flights = cursor.fetchall()

        cursor.close()
        connection.close()

        if not filtered_flights:
            flash('No flights available', 'danger')

        return render_template('search.html', flights=filtered_flights)

    return render_template('search.html', flights=None)

# Route for flight selection
@app.route('/flight-selection', methods=['GET'])
@login_required
def flight_selection():
    origin = request.args.get('origin')
    destination = request.args.get('destination')

    # Optional parameters (not used for filtering)
    trip_type = request.args.get('tripType')
    departure_date = request.args.get('departureDate')
    return_date = request.args.get('returnDate')
    passengers = request.args.get('passengers')
    class_type = request.args.get('classType')

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Query flights from the database based on origin and destination
    query = """
        SELECT * FROM flights
        WHERE source = %s AND destination = %s
    """
    cursor.execute(query, (origin, destination))
    filtered_flights = cursor.fetchall()

    cursor.close()
    connection.close()

    # Group flights by flight_number
    flights_by_number = defaultdict(list)
    for flight in filtered_flights:
        flights_by_number[flight['flight_number']].append(flight)

    # Pass the filtered flights and optional parameters to the template
    return render_template(
        'flight-selection.html',
        flights_by_number=flights_by_number,
        origin=origin,
        destination=destination,
        trip_type=trip_type,
        departure_date=departure_date,
        return_date=return_date,
        passengers=passengers,
        class_type=class_type
    )

# Route for booking a flight
@app.route('/book/<int:flight_id>', methods=['POST'])
@login_required
def book_flight(flight_id):
    passenger_name = request.form.get('passenger_name')

    connection = get_db_connection()
    cursor = connection.cursor()

    # Insert booking into the database
    cursor.execute(
        "INSERT INTO bookings (flight_id, username, passenger_name, booking_date) VALUES (%s, %s, %s, NOW())",
        (flight_id, session['username'], passenger_name)
    )
    connection.commit()

    # Send a notification to the user
    cursor.execute(
        "INSERT INTO notifications (username, message) VALUES (%s, %s)",
        (session['username'], f"Your flight with ID {flight_id} has been successfully booked.")
    )
    connection.commit()

    cursor.close()
    connection.close()

    flash('Flight booked successfully!', 'success')
    return redirect(url_for('bookings'))

# Route for payment page
@app.route('/payment', methods=['GET', 'POST'])
@login_required
def payment():
    MINIMUM_POINTS_FOR_REDEMPTION = 50  # Minimum points required to redeem

    flight_id = request.args.get('flight_id')
    if flight_id is None:
        flash('Flight ID is missing.', 'danger')
        return redirect(url_for('home'))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch the flight from the database
    cursor.execute("SELECT * FROM flights WHERE id = %s", (flight_id,))
    flight = cursor.fetchone()

    if flight is None:
        cursor.close()
        connection.close()
        flash('Flight not found.', 'danger')
        return redirect(url_for('home'))

    # Fetch user's loyalty points
    cursor.execute("""
        SELECT points, total_points_left FROM loyalty_points
        WHERE user_id = (SELECT id FROM users WHERE username = %s)
    """, (session['username'],))
    loyalty_points = cursor.fetchone()
    available_points = loyalty_points['total_points_left'] if loyalty_points else 0

    if request.method == 'POST':
        passenger_name = request.form.get('passenger_name')
        payment_method = request.form.get('payment_method')  # e.g., credit_card, paypal
        points_to_redeem = int(request.form.get('points_to_redeem', 0))

        if not passenger_name:
            flash('Passenger name is required.', 'danger')
            return redirect(url_for('payment', flight_id=flight_id))

        # Check if the user has enough points to redeem
        if points_to_redeem > available_points:
            flash('You do not have enough loyalty points to redeem.', 'danger')
            return redirect(url_for('payment', flight_id=flight_id))

        # Check if the points to redeem meet the minimum threshold
        if points_to_redeem > 0 and points_to_redeem < MINIMUM_POINTS_FOR_REDEMPTION:
            flash(f'You must redeem at least {MINIMUM_POINTS_FOR_REDEMPTION} points.', 'danger')
            return redirect(url_for('payment', flight_id=flight_id))

        # Calculate discount and final price
        discount = points_to_redeem * 0.1  # Example: 1 point = $0.10
        final_price = max(0, float(flight['price']) - discount)

        # Calculate loyalty points earned (e.g., 1 point per $10 spent)
        loyalty_points_earned = int(final_price // 10)

        try:
            # Insert booking into the database
            cursor.execute(
                """
                INSERT INTO bookings (flight_id, username, passenger_name, booking_date, payment_status, final_price)
                VALUES (%s, %s, %s, NOW(), %s, %s)
                """,
                (flight_id, session['username'], passenger_name, 'confirmed', final_price)
            )
            connection.commit()

            # Get the booking ID
            booking_id = cursor.lastrowid

            # Insert transaction into the database
            cursor.execute(
                """
                INSERT INTO transactions (booking_id, username, amount, transaction_type, status, payment_method, discount_applied)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (booking_id, session['username'], final_price, 'payment', 'success', payment_method, discount)
            )
            connection.commit()

            # Update loyalty points table
            if loyalty_points:
                # Update existing loyalty points
                cursor.execute("""
                    UPDATE loyalty_points
                    SET points = points + %s, total_points_left = total_points_left - %s + %s
                    WHERE user_id = (SELECT id FROM users WHERE username = %s)
                """, (loyalty_points_earned, points_to_redeem, loyalty_points_earned, session['username']))
            else:
                # Insert new loyalty points record
                cursor.execute("""
                    INSERT INTO loyalty_points (user_id, points, total_points_left)
                    VALUES ((SELECT id FROM users WHERE username = %s), %s, %s)
                """, (session['username'], loyalty_points_earned, loyalty_points_earned - points_to_redeem))
            connection.commit()

            # Notify the user about the booking confirmation
            cursor.execute(
                "INSERT INTO notifications (username, message) VALUES (%s, %s)",
                (session['username'], f"Booking confirmed! Flight from {flight['source']} to {flight['destination']} on {flight['departure_date']}. Final price: ${final_price:.2f}.")
            )
            connection.commit()

            # Notify the user about the discount applied
            if points_to_redeem > 0:
                cursor.execute(
                    "INSERT INTO notifications (username, message) VALUES (%s, %s)",
                    (session['username'], f"You redeemed {points_to_redeem} points and received a discount of ${discount:.2f}.")
                )
                connection.commit()

            # Notify the user about the points earned
            if loyalty_points_earned > 0:
                cursor.execute(
                    "INSERT INTO notifications (username, message) VALUES (%s, %s)",
                    (session['username'], f"You earned {loyalty_points_earned} loyalty points for this booking.")
                )
                connection.commit()

            flash('Payment confirmed successfully!', 'success')
        except Exception as e:
            connection.rollback()
            print(f"Error processing payment: {e}")
            flash('An error occurred while processing the payment.', 'danger')
            return redirect(url_for('payment', flight_id=flight_id))
        finally:
            cursor.close()
            connection.close()

        return redirect(url_for('bookings'))

    cursor.close()
    connection.close()
    return render_template('payment.html', flight=flight, available_points=available_points)

# Route for ticket confirmation
@app.route('/ticket')
@login_required
def ticket():
    booking_id = request.args.get('booking_id')

    if not booking_id:
        return "Booking ID is missing."

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch the booking and flight details using booking_id
    cursor.execute("""
        SELECT f.*, b.passenger_name
        FROM bookings b
        JOIN flights f ON b.flight_id = f.id
        WHERE b.id = %s AND b.username = %s
    """, (booking_id, session['username']))
    ticket_details = cursor.fetchone()

    cursor.close()
    connection.close()

    if not ticket_details:
        return "Ticket not found."

    # Pass the ticket details to the template
    return render_template('ticket.html', flight=ticket_details, passenger_name=ticket_details['passenger_name'])

# Route for viewing bookings
@app.route('/bookings')
@login_required
def bookings():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch bookings for the logged-in user
    cursor.execute("""
        SELECT b.id AS booking_id, f.flight_number, f.source, f.destination, 
               f.departure_date, b.final_price AS price, 
               b.passenger_name, b.booking_date, b.status
        FROM bookings b
        JOIN flights f ON b.flight_id = f.id
        WHERE b.username = %s
    """, (session['username'],))
    bookings = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('bookings.html', bookings=bookings)

# Route for cancelling a booking
@app.route('/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch booking details for the notification
    cursor.execute("""
        SELECT f.source, f.destination, f.departure_date
        FROM bookings b
        JOIN flights f ON b.flight_id = f.id
        WHERE b.id = %s AND b.username = %s
    """, (booking_id, session['username']))
    booking = cursor.fetchone()

    if not booking:
        flash('Invalid booking ID or unauthorized access.', 'danger')
        return redirect(url_for('bookings'))

    # Update the booking status to 'cancelled'
    cursor.execute(
        "UPDATE bookings SET status = %s WHERE id = %s AND username = %s",
        ('cancelled', booking_id, session['username'])
    )
    connection.commit()

    # Send a notification to the user
    cursor.execute(
        "INSERT INTO notifications (username, message) VALUES (%s, %s)",
        (session['username'], f"Your booking from {booking['source']} to {booking['destination']} on {booking['departure_date']} has been canceled.")
    )
    connection.commit()

    cursor.close()
    connection.close()

    flash('Booking cancelled successfully!', 'success')
    return redirect(url_for('bookings'))

# Route for transactions
@app.route('/transactions')
@login_required
def transactions():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch transactions for the logged-in user
    cursor.execute("""
        SELECT t.id, t.booking_id, t.amount AS amount, t.discount_applied, 
               t.transaction_type, t.transaction_date, t.status, t.payment_method, 
               f.flight_number, f.source, f.destination
        FROM transactions t
        JOIN bookings b ON t.booking_id = b.id
        JOIN flights f ON b.flight_id = f.id
        WHERE t.username = %s
        ORDER BY t.transaction_date DESC
    """, (session['username'],))
    transactions = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('transactions.html', transactions=transactions)

# Route for feedback
@app.route('/feedback/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def feedback(booking_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Check if the booking exists and belongs to the logged-in user
    cursor.execute("""
        SELECT * FROM bookings WHERE id = %s AND username = %s
    """, (booking_id, session['username']))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        connection.close()
        flash('Invalid booking ID or unauthorized access.', 'danger')
        return redirect(url_for('bookings'))

    if request.method == 'POST':
        rating = request.form.get('rating')
        comments = request.form.get('comments')

        # Insert feedback into the database
        cursor.execute("""
            INSERT INTO feedback (booking_id, username, rating, comments)
            VALUES (%s, %s, %s, %s)
        """, (booking_id, session['username'], rating, comments))
        connection.commit()

        flash('Thank you for your feedback!', 'success')
        cursor.close()
        connection.close()
        return redirect(url_for('bookings'))

    cursor.close()
    connection.close()

    return render_template('feedback.html', booking=booking)

# Route for notifications
@app.route('/notifications')
@login_required
def notifications():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch notifications for the logged-in user
    cursor.execute("""
        SELECT * FROM notifications WHERE username = %s ORDER BY created_at DESC
    """, (session['username'],))
    notifications = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('notifications.html', notifications=notifications)

@app.route('/notifications/mark-as-read', methods=['POST'])
@login_required
def mark_notifications_as_read():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Mark all notifications as read for the logged-in user
    cursor.execute("""
        UPDATE notifications SET is_read = TRUE WHERE username = %s
    """, (session['username'],))
    connection.commit()

    cursor.close()
    connection.close()

    flash('All notifications marked as read.', 'success')
    return redirect(url_for('notifications'))

# Route for loyalty points
@app.route('/loyalty-points')
@login_required
def loyalty_points():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch loyalty points for the logged-in user
    cursor.execute("""
        SELECT total_points_left FROM loyalty_points
        WHERE user_id = (SELECT id FROM users WHERE username = %s)
    """, (session['username'],))
    points = cursor.fetchone()

    cursor.close()
    connection.close()

    return render_template('loyalty_points.html', points=points['total_points_left'] if points else 0)

# Route for logout
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# Route for refunds
@app.route('/refunds')
@login_required
def refunds():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.id, b.final_price AS price, b.refund_status, f.flight_number, f.departure_date
        FROM bookings b
        JOIN flights f ON b.flight_id = f.id
        WHERE b.username = %s AND b.status = 'cancelled'
    """, (session['username'],))
    cancelled_bookings = cursor.fetchall()
    cursor.close()
    connection.close()
    return render_template('refunds.html', bookings=cancelled_bookings)

@app.route('/request_refund/<int:booking_id>', methods=['POST'])
@login_required
def request_refund(booking_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    # Update booking refund status
    cursor.execute("""
        UPDATE bookings SET refund_status = 'REFUNDED'
        WHERE id = %s AND username = %s AND status = 'cancelled'
    """, (booking_id, session['username']))
    # Update transaction status to refunded where it was success
    cursor.execute("""
        UPDATE transactions SET status = 'refunded'
        WHERE booking_id = %s AND username = %s AND status = 'success'
    """, (booking_id, session['username']))
    connection.commit()
    cursor.close()
    connection.close()
    flash('Refund processed successfully!', 'success')
    return redirect(url_for('refunds'))

 
# Route for help page
@app.route('/help')
@login_required
def help_page():
    return render_template('help.html')

# Run the app
if __name__ == '__main__':

    app.run(debug=True)

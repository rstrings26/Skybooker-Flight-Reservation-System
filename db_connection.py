# filepath: c:\ars\ars\database\db_connection.py
import mysql.connector

def get_db_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",  # Replace with your MySQL username
        password="",  # Replace with your MySQL password
        database="flight_booking"
       
    )
    return connection
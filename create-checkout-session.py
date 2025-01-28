import os
import stripe
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Route to create a Stripe Checkout Session
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data = request.get_json()
    package_minutes = data.get("minutes")  # 10, 30, or 60 minutes
    price_lookup = {
        10: "price_10min",  # Replace with your actual price ID from Stripe Dashboard
        30: "price_30min",
        60: "price_60min"
    }
    
    # Validate the requested package
    if package_minutes not in price_lookup:
        return jsonify({"error": "Invalid package"}), 400
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_lookup[package_minutes],  # The price ID for the selected package
                "quantity": 1
            }],
            mode="payment",  # One-time payment
            success_url="https://yourdomain.com/success",
            cancel_url="https://yourdomain.com/cancel"
        )
        
        return jsonify({"url": session.url})  # Return the checkout session URL
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Route to handle Stripe webhook events
@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_email = session["customer_email"]
        minutes_purchased = session["amount_total"] // 100  # Assuming 1 USD = 1 minute of credit

        # Update the user's credit balance in the database
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO credits (user_id, balance_minutes)
                VALUES ((SELECT id FROM users WHERE email = %s), %s)
                ON DUPLICATE KEY UPDATE balance_minutes = balance_minutes + %s
            """, (user_email, minutes_purchased, minutes_purchased))
            connection.commit()

        return jsonify({"status": "success"})
    
    return jsonify({"status": "unhandled event"})


# Route to consume credits (user uses minutes)
@app.route("/use-minutes", methods=["POST"])
def use_minutes():
    user_email = request.json.get("email")
    minutes_to_consume = request.json.get("minutes")

    # Check if the user has enough balance
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT balance_minutes FROM credits
            WHERE user_id = (SELECT id FROM users WHERE email = %s)
        """, (user_email,))
        result = cursor.fetchone()

    if result and result[0] >= minutes_to_consume:
        # Deduct minutes from the user's balance
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE credits
                SET balance_minutes = balance_minutes - %s
                WHERE user_id = (SELECT id FROM users WHERE email = %s)
            """, (minutes_to_consume, user_email))
            connection.commit()
        
        return jsonify({"status": "minutes used", "remaining_minutes": result[0] - minutes_to_consume})
    else:
        return jsonify({"error": "Insufficient balance"}), 400


if __name__ == "__main__":
    app.run(debug=True)

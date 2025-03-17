from flask import Flask, render_template, request, redirect, url_for, flash, session
import numpy as np
import cvxpy as cp
import psycopg2
import secrets
import os

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Clé secrète aléatoire

#------------------------------------------------------------- Connection à PostgreSQL -------------------------------------------------------

# Configuration pour Render
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://maarahot_meida_user:fIhWvtfELWeDflGXVi4Kseh9D4p0LJd0@dpg-cvc87s2n91rc73cbu5dg-a.frankfurt-postgres.render.com/maarahot_meida')

def get_db_connection():
    """Établit et retourne une connexion à la base de données PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

#------------------------------------------------------------- Gestion des utilisateurs -------------------------------------------------------

def insert_user(first_name, last_name, income, expenses):
    """Insère un utilisateur dans la base de données et retourne son ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Vérifier si l'utilisateur existe déjà
            query_check = "SELECT UserID FROM Users WHERE FirstName = %s AND LastName = %s"
            cursor.execute(query_check, (first_name, last_name))
            existing_user = cursor.fetchone()
            
            if existing_user:
                return existing_user[0]
            
            # Insérer le nouvel utilisateur
            query = """
            INSERT INTO Users (FirstName, LastName, Income, Expenses) 
            VALUES (%s, %s, %s, %s)
            RETURNING UserID
            """
            cursor.execute(query, (first_name, last_name, income, expenses))
            user_id = cursor.fetchone()[0]
            conn.commit()
            return user_id
        except psycopg2.Error as e:
            print(f"Database insertion error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    return None

def get_user_id(first_name, last_name):
    """Récupère l'ID de l'utilisateur."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "SELECT UserID FROM Users WHERE FirstName = %s AND LastName = %s"
            cursor.execute(query, (first_name, last_name))
            result = cursor.fetchone()
            return result[0] if result else None
        except psycopg2.Error as e:
            print(f"Database query error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    return None

@app.route("/")
def home():
    if 'initialized' not in session:
        session.clear()
        session['initialized'] = True
        session['budget'] = {"income": 0, "expenses": 0, "available": 0}
        session['objectives'] = []
        session['user_info'] = {}
        session['user_id'] = None  # Ajouter un ID utilisateur à la session

    return render_template("budget.html", 
                         budget=session['budget'],
                         user_info=session['user_info'])

@app.route("/set_budget", methods=["POST"])
def set_budget():
    first_name = request.form.get("firstName")
    last_name = request.form.get("lastName")
    income = int(request.form.get("income"))
    expenses = int(request.form.get("expenses"))

    if expenses > income:
        flash("Impossible budget: your monthly expenses exceed your income. Please adjust your amounts.", "error")
        return redirect(url_for("home"))

    # Insérer l'utilisateur et récupérer son ID
    user_id = insert_user(first_name, last_name, income, expenses)
    
    # Stocker l'ID utilisateur dans la session
    session['user_id'] = user_id
    
    session['user_info'] = {
        "firstName": first_name,
        "lastName": last_name
    }

    session['budget'] = {
        "income": income,
        "expenses": expenses,
        "available": int((income - expenses) * 0.9)
    }

    return redirect(url_for("objectives_page"))

#------------------------------------------------------------- Gestion des objectifs -------------------------------------------------------

def insert_plan(plan_name, duration, amount, user_id):
    """Insère un plan et crée l'association avec l'utilisateur."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Insérer le plan
            cursor.execute("""
                INSERT INTO Plans (PlanName, SumOfMonths, SumOfMoney) 
                VALUES (%s, %s, %s)
                RETURNING PlanID
            """, (plan_name, duration, amount))
            plan_id = cursor.fetchone()[0]
            
            # Créer l'association dans la table UserPlans
            cursor.execute("""
                INSERT INTO UserPlans (UserID, PlanID)
                VALUES (%s, %s)
            """, (user_id, plan_id))
            
            conn.commit()
            return plan_id
        except psycopg2.Error as e:
            print(f"Database insertion error: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()
            conn.close()
    return None

@app.route("/objectives")
def objectives_page():
    # Vérifier si l'ID utilisateur est dans la session
    if 'user_id' not in session or not session['user_id']:
        # Si pas d'ID utilisateur, rediriger vers la page d'accueil
        flash("Please enter your budget information first.", "error")
        return redirect(url_for("home"))
        
    return render_template("objectives.html", 
                         objectives=session.get('objectives', []), 
                         budget=session.get('budget', {}))

@app.route("/add_objective", methods=["POST"])
def add_objective():
    # Utiliser l'ID utilisateur de la session au lieu de le rechercher
    user_id = session.get('user_id')
    
    if not user_id:
        flash("User not found. Please enter your budget first.", "error")
        return redirect(url_for("home"))

    plan_name = request.form.get("objectiveName")
    duration = int(request.form.get("duration"))
    amount = int(request.form.get("amount"))

    if duration > 12:
        flash("The duration of a goal cannot exceed 12 months.", "error")
        return redirect(url_for("objectives_page"))

    # Passer l'ID utilisateur à la fonction insert_plan
    plan_id = insert_plan(plan_name, duration, amount, user_id)
    
    if 'objectives' not in session:
        session['objectives'] = []

    session['objectives'].append({
        "name": plan_name,
        "duration": duration,
        "amount": amount
    })
    
    # S'assurer que les modifications de la session sont enregistrées
    session.modified = True

    return redirect(url_for("objectives_page"))

#------------------------------------------------------------- Sauvegarde des résultats -------------------------------------------------------

def insert_optimization_results(user_id, savings):
    """Insère les résultats de l'optimisation pour un utilisateur dans Outputs."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = """
            INSERT INTO Outputs (UserID, Month1, Month2, Month3, Month4, Month5, Month6, 
                                Month7, Month8, Month9, Month10, Month11, Month12) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, [user_id] + savings)
            conn.commit()
            return True
        except psycopg2.Error as e:
            print(f"Database insertion error: {e}")
            return False
        finally:
            cursor.close()
            conn.close()
    return False

@app.route("/optimization_results", methods=["POST"])
def optimization_results():
    # Utiliser l'ID utilisateur de la session
    user_id = session.get('user_id')

    if not user_id:
        flash("User not found. Please enter your budget first.", "error")
        return redirect(url_for("home"))

    objectives = session.get('objectives', [])
    budget = session.get('budget', {})

    if not objectives:
        flash("No goals added. Please add at least one goal.", "error")
        return redirect(url_for("objectives_page"))

    if budget["available"] <= 0:
        flash("Your available budget is insufficient.", "error")
        return redirect(url_for("objectives_page"))

    max_months = 12
    savings = np.zeros(max_months)

    for obj in objectives:
        per_month = obj["amount"] / obj["duration"]
        for i in range(obj["duration"]):
            savings[i] += per_month

    savings = [round(x, 2) for x in savings]

    # Insérer les résultats avec l'ID utilisateur de la session
    success = insert_optimization_results(user_id, savings)
    
    if not success:
        flash("There was an error saving your results.", "error")
        return redirect(url_for("objectives_page"))

    results = [{"month": i + 1, "saving": savings[i]} for i in range(max_months)]
    total_saved = round(sum(savings), 2)

    return render_template("results.html", results=results, total_saved=total_saved)

# Route pour supprimer un objectif (pour compléter la fonctionnalité dans objectives.html)
@app.route("/delete_objective", methods=["POST"])
def delete_objective():
    objective_name = request.form.get("objectiveName")
    
    if 'objectives' in session:
        session['objectives'] = [obj for obj in session['objectives'] if obj['name'] != objective_name]
        session.modified = True
    
    return redirect(url_for("objectives_page"))

# Script pour créer les tables nécessaires dans PostgreSQL
def create_tables():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Créer la table Users
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Users (
                    UserID SERIAL PRIMARY KEY,
                    FirstName VARCHAR(100) NOT NULL,
                    LastName VARCHAR(100) NOT NULL,
                    Income NUMERIC NOT NULL,
                    Expenses NUMERIC NOT NULL
                )
            """)
            
            # Créer la table Plans
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Plans (
                    PlanID SERIAL PRIMARY KEY,
                    PlanName VARCHAR(100) NOT NULL,
                    SumOfMonths INTEGER NOT NULL,
                    SumOfMoney NUMERIC NOT NULL
                )
            """)
            
            # Créer la table UserPlans
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS UserPlans (
                    UserPlanID SERIAL PRIMARY KEY,
                    UserID INTEGER REFERENCES Users(UserID),
                    PlanID INTEGER REFERENCES Plans(PlanID)
                )
            """)
            
            # Créer la table Outputs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Outputs (
                    OutputID SERIAL PRIMARY KEY,
                    UserID INTEGER REFERENCES Users(UserID),
                    Month1 NUMERIC,
                    Month2 NUMERIC,
                    Month3 NUMERIC,
                    Month4 NUMERIC,
                    Month5 NUMERIC,
                    Month6 NUMERIC,
                    Month7 NUMERIC,
                    Month8 NUMERIC,
                    Month9 NUMERIC,
                    Month10 NUMERIC,
                    Month11 NUMERIC,
                    Month12 NUMERIC
                )
            """)
            
            conn.commit()
            print("Tables created successfully")
        except psycopg2.Error as e:
            print(f"Error creating tables: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    # Créer les tables au démarrage de l'application
    create_tables()
    # Configurer le port pour Render (utilise la variable d'environnement PORT ou 8000 par défaut)
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
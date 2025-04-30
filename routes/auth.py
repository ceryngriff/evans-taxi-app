from flask import Blueprint, render_template, request, redirect, url_for, flash
from model import Manager, Driver, Escort, Mechanic
from flask_login import login_user
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

# MANAGER LOGIN
@auth_bp.route('/manager-login', methods=['GET', 'POST'])   
def manager_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        manager = Manager.query.filter_by(username=username).first()
        if manager and check_password_hash(manager.password, password):
            login_user(manager)
            flash('Manager login successful!', 'success')
            return redirect(url_for('manager_dashboard'))

        flash('Invalid credentials', 'danger')
    return render_template('manager_login.html')


# STAFF LOGIN (Drivers and Escorts)
@auth_bp.route('/staff-login', methods=['GET', 'POST'])
def staff_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = Driver.query.filter_by(username=username).first()
        if not user:
            user = Escort.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Staff login successful!', 'success')
            return redirect(url_for('staff_dashboard'))

        flash('Invalid credentials', 'danger')
    return render_template('staff_login.html')


# MECHANIC LOGIN

@auth_bp.route('/mechanic-login', methods=['GET', 'POST'])
def mechanic_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        mechanic = Mechanic.query.filter_by(username=username).first()
        if mechanic and check_password_hash(mechanic.password, password):
            if mechanic.role == 'mechanic':
                login_user(mechanic)
                flash('Mechanic login successful!', 'success')
                return redirect(url_for('mechanic.dashboard'))
            else:
                flash('Unauthorized access for this role.', 'danger')
                return redirect(url_for('auth.mechanic_login'))
        else:
            flash('Invalid credentials.', 'danger')
    return render_template('login_mechanics.html')



# stockmon.py - Combined Stock Monitoring and Investment Tracking App
import os
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, jsonify
import pandas as pd
import sqlite3
from datetime import datetime
import plotly.express as px
import plotly.io as pio
from flask_sqlalchemy import SQLAlchemy

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['STOCK_DATABASE'] = 'stocks.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///investments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy for investments
db = SQLAlchemy(app)

# Investment Models
class Investment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    platform = db.Column(db.String(100), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    actual_amount = db.Column(db.Float, default=0.0)
    profit_loss = db.Column(db.Float, default=0.0)
    transactions = db.relationship('Transaction', backref='investment', lazy=True)

    def __repr__(self):
        return f'<Investment {self.name}>'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    investment_id = db.Column(db.Integer, db.ForeignKey('investment.id'), nullable=False)
    notes = db.Column(db.String(200))

    def __repr__(self):
        return f'<Transaction {self.date} {self.amount}>'

class Portfolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), nullable=False)
    shares = db.Column(db.Float, nullable=False)
    average_price = db.Column(db.Float, nullable=False)
    latest_price = db.Column(db.Float)
    account = db.Column(db.String(100), nullable=False)
    investment_id = db.Column(db.Integer, db.ForeignKey('investment.id'))
    
    @property
    def total_cost(self):
        return self.shares * self.average_price
    
    @property
    def market_value(self):
        return self.shares * (self.latest_price if self.latest_price else self.average_price)
    
    @property
    def profit(self):
        return self.market_value - self.total_cost

class InvestmentSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    total_invested = db.Column(db.Float, nullable=False)
    current_value = db.Column(db.Float, nullable=False)
    profit_loss = db.Column(db.Float, nullable=False)
    profit_loss_pct = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<InvestmentSnapshot {self.date}>'

class AccountSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    account_name = db.Column(db.String(100), nullable=False)
    goal = db.Column(db.String(100), nullable=False)
    platform = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    total_invested = db.Column(db.Float, nullable=False)
    current_value = db.Column(db.Float, nullable=False)
    profit_loss = db.Column(db.Float, nullable=False)
    profit_loss_pct = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<AccountSnapshot {self.account_name} {self.date}>'

# Create tables
with app.app_context():
    db.create_all()

# Initialize stock database
def init_stock_db():
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            nfb_nfs REAL,
            UNIQUE(symbol, date)
        );
        ''')
        conn.commit()

init_stock_db()

# Stock Monitoring Routes
@app.route('/stocks')
def index():
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        # Get the most recent date across all stocks
        latest_date = pd.read_sql('SELECT MAX(date) as max_date FROM stocks', conn)['max_date'].iloc[0]
        
        # Get all data for the latest date only with all columns
        latest_data = pd.read_sql('''
            SELECT symbol, date, open, high, low, close, volume, nfb_nfs 
            FROM stocks 
            WHERE date = ?
            ORDER BY symbol
        ''', conn, params=(latest_date,))
        
        # Calculate changes (if previous day data exists)
        previous_closes = []
        for symbol in latest_data['symbol']:
            previous_close = pd.read_sql('''
                SELECT close FROM stocks 
                WHERE symbol = ? AND date < ?
                ORDER BY date DESC 
                LIMIT 1
            ''', conn, params=(symbol, latest_date))['close'].iloc[0] if pd.read_sql('''
                SELECT COUNT(*) as count FROM stocks 
                WHERE symbol = ? AND date < ?
            ''', conn, params=(symbol, latest_date))['count'].iloc[0] > 0 else None
            previous_closes.append({'symbol': symbol, 'previous_close': previous_close})
        
        previous_closes_df = pd.DataFrame(previous_closes)
        latest_data = pd.merge(latest_data, previous_closes_df, on='symbol')
        
        # Calculate price change percentage
        latest_data['change_pct'] = latest_data.apply(
            lambda row: ((row['close'] - row['previous_close']) / row['previous_close'] * 100 
                        if row['previous_close'] and row['previous_close'] != 0 
                        else 0), 
            axis=1
        ).round(2)
        
        # Get all available symbols for the dropdown
        symbols = pd.read_sql('SELECT DISTINCT symbol FROM stocks ORDER BY symbol', conn)['symbol'].tolist()

    # Get portfolio symbols (stocks the user holds)
    portfolio_symbols = sorted(set(
        p.symbol for p in Portfolio.query.filter(Portfolio.symbol != 'NON-STOCK').all()
    ))

    return render_template('main.html',
                         stocks=latest_data.to_dict('records'),
                         symbols=symbols,
                         portfolio_symbols=portfolio_symbols,
                         latest_date=latest_date)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'folder' not in request.files:
            flash('No folder selected')
            return redirect(request.url)
        
        files = request.files.getlist('folder')
        if not files or files[0].filename == '':
            flash('No files selected in folder')
            return redirect(request.url)
        
        processed_files = 0
        total_records = 0
        
        for file in files:
            if file and file.filename.lower().endswith('.csv'):
                try:
                    # Read and process the CSV file
                    expected_columns = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'nfb_nfs']
                    df = pd.read_csv(file, header=0)

                    # Standardize column names
                    df.columns = df.columns.str.lower()
                    if 'nfb/nfs' in df.columns:
                        df = df.rename(columns={'nfb/nfs': 'nfb_nfs'})

                    # Detect headerless CSV: if first column name looks like a stock symbol (no 'symbol'/'date' header)
                    if 'date' not in df.columns:
                        file.seek(0)
                        df = pd.read_csv(file, header=None, names=expected_columns)
                    
                    # Convert date to consistent format
                    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                    
                    # Get unique dates from the current file
                    unique_dates = df['date'].unique()
                    
                    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
                        # Delete existing records with matching dates
                        cursor = conn.cursor()
                        placeholders = ','.join(['?'] * len(unique_dates))
                        cursor.execute(
                            f'DELETE FROM stocks WHERE date IN ({placeholders})', 
                            tuple(unique_dates)
                        )
                        conn.commit()
                        
                        # Insert new records
                        df.to_sql('stocks', conn, if_exists='append', index=False)
                    
                    processed_files += 1
                    total_records += len(df)
                
                except Exception as e:
                    flash(f'Error processing file {file.filename}: {str(e)}')
                    continue
        
        if processed_files > 0:
            flash(f'Successfully processed {processed_files} files with {total_records} total records')
        else:
            flash('No valid CSV files found in the selected folder')
        
        return redirect(url_for('index'))
    
    return render_template('upload.html')

@app.route('/symbol/<symbol>')
def symbol_detail(symbol):
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        # Get all data for this symbol
        df = pd.read_sql(f'''
        SELECT date, open, high, low, close, volume
        FROM stocks
        WHERE symbol = ?
        ORDER BY date
        ''', conn, params=(symbol,))

        # Get latest price
        latest = pd.read_sql(f'''
        SELECT *
        FROM stocks
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT 1
        ''', conn, params=(symbol,)).iloc[0].to_dict()

    if df.empty:
        flash(f'No data found for symbol {symbol}')
        return redirect(url_for('index'))

    # Compute performance stats
    high_52w = float(df['high'].max()) if not df.empty else None
    low_52w = float(df['low'].min()) if not df.empty else None
    avg_volume = float(df['volume'].mean()) if not df.empty else None

    # Pass OHLCV data as JSON for client-side candlestick chart
    ohlcv = df.to_dict(orient='list')

    return render_template('symbol.html',
                         symbol=symbol,
                         latest=latest,
                         ohlcv=ohlcv,
                         high_52w=high_52w,
                         low_52w=low_52w,
                         avg_volume=avg_volume)

# Investment Tracking Routes
@app.route('/')
@app.route('/investments')
def investments():
    investments = Investment.query.all()
    portfolios = Portfolio.query.all()
    
    # Update latest prices from stock data
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        for p in portfolios:
            latest_price = pd.read_sql('''
                SELECT close FROM stocks 
                WHERE symbol = ? 
                ORDER BY date DESC 
                LIMIT 1
            ''', conn, params=(p.symbol,))['close'].iloc[0] if pd.read_sql('''
                SELECT COUNT(*) as count FROM stocks 
                WHERE symbol = ?
            ''', conn, params=(p.symbol,))['count'].iloc[0] > 0 else None
            
            if latest_price:
                p.latest_price = latest_price
                db.session.commit()
    
    return render_template('investments/index.html', 
                         investments=investments,
                         portfolios=portfolios,
                         now=datetime.now)

@app.route('/investments/save-snapshot', methods=['POST'])
def save_snapshot():
    data = request.get_json()
    snapshot = InvestmentSnapshot(
        total_invested=data['total_invested'],
        current_value=data['current_value'],
        profit_loss=data['profit_loss'],
        profit_loss_pct=data['profit_loss_pct']
    )
    db.session.add(snapshot)
    db.session.commit()
    return jsonify({'status': 'success', 'id': snapshot.id, 'date': snapshot.date.strftime('%Y-%m-%d %H:%M')})

@app.route('/investments/snapshots')
def investment_snapshots():
    snapshots = InvestmentSnapshot.query.order_by(InvestmentSnapshot.date.desc()).all()
    return jsonify([{
        'id': s.id,
        'date': s.date.strftime('%Y-%m-%d %H:%M'),
        'total_invested': s.total_invested,
        'current_value': s.current_value,
        'profit_loss': s.profit_loss,
        'profit_loss_pct': s.profit_loss_pct
    } for s in snapshots])

@app.route('/investments/snapshots/<int:id>', methods=['DELETE'])
def delete_snapshot(id):
    snapshot = InvestmentSnapshot.query.get_or_404(id)
    db.session.delete(snapshot)
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/investments/save-account-snapshot', methods=['POST'])
def save_account_snapshot():
    data = request.get_json()
    accounts = data.get('accounts', [])
    saved = 0
    for acct in accounts:
        snapshot = AccountSnapshot(
            account_name=acct['account_name'],
            goal=acct['goal'],
            platform=acct['platform'],
            type=acct['type'],
            total_invested=acct['total_invested'],
            current_value=acct['current_value'],
            profit_loss=acct['profit_loss'],
            profit_loss_pct=acct['profit_loss_pct']
        )
        db.session.add(snapshot)
        saved += 1
    db.session.commit()
    return jsonify({'status': 'success', 'saved': saved, 'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')})

@app.route('/investments/account-history')
def account_history():
    accounts = db.session.query(AccountSnapshot.account_name).distinct().order_by(AccountSnapshot.account_name).all()
    account_list = [a[0] for a in accounts]
    return render_template('investments/account_history.html', accounts=account_list)

@app.route('/investments/account-snapshots')
def account_snapshots():
    account = request.args.get('account', '')
    query = AccountSnapshot.query.order_by(AccountSnapshot.date.desc())
    if account:
        query = query.filter_by(account_name=account)
    snapshots = query.all()
    return jsonify([{
        'id': s.id,
        'date': s.date.strftime('%Y-%m-%d %H:%M'),
        'account_name': s.account_name,
        'goal': s.goal,
        'platform': s.platform,
        'type': s.type,
        'total_invested': s.total_invested,
        'current_value': s.current_value,
        'profit_loss': s.profit_loss,
        'profit_loss_pct': s.profit_loss_pct
    } for s in snapshots])

@app.route('/investments/account-snapshots/<int:id>', methods=['DELETE'])
def delete_account_snapshot(id):
    snapshot = AccountSnapshot.query.get_or_404(id)
    db.session.delete(snapshot)
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/investments/account-snapshots/bulk-delete', methods=['DELETE'])
def bulk_delete_account_snapshots():
    account = request.args.get('account', '')
    date = request.args.get('date', '')
    query = AccountSnapshot.query
    if account:
        query = query.filter_by(account_name=account)
    if date:
        query = query.filter(db.func.strftime('%Y-%m-%d', AccountSnapshot.date) == date)
    count = query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'status': 'success', 'deleted': count})

@app.route('/investments/add', methods=['GET', 'POST'])
def add_investment():
    if request.method == 'POST':
        name = request.form['name']
        platform = request.form['platform']
        account_name = request.form['account_name']
        investment_type = request.form['type']

        initial_amount_str = request.form.get('initial_amount', '0').strip()
        initial_amount = float(initial_amount_str) if initial_amount_str else 0.0

        investment = Investment(
            name=name,
            platform=platform,
            account_name=account_name,
            type=investment_type,
            total_amount=initial_amount,
            actual_amount=initial_amount
        )

        db.session.add(investment)
        db.session.commit()

        if initial_amount > 0:
            transaction = Transaction(
                date=datetime.now().date(),
                amount=initial_amount,
                investment_id=investment.id,
                notes="Initial investment"
            )
            db.session.add(transaction)
            db.session.commit()

        filter_goal = request.form.get('filter_goal', '')
        filter_account = request.form.get('filter_account', '')
        filter_type = request.form.get('filter_type', '')
        return redirect(url_for('investments', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type))

    filter_goal = request.args.get('filter_goal', '')
    filter_account = request.args.get('filter_account', '')
    filter_type = request.args.get('filter_type', '')
    return render_template('investments/add_investment.html', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type)

@app.route('/investments/edit/<int:id>', methods=['GET', 'POST'])
def edit_investment(id):
    investment = Investment.query.get_or_404(id)

    if request.method == 'POST':
        investment.name = request.form['name']
        investment.platform = request.form['platform']
        investment.account_name = request.form['account_name']
        investment.type = request.form['type']
        db.session.commit()
        filter_goal = request.form.get('filter_goal', '')
        filter_account = request.form.get('filter_account', '')
        filter_type = request.form.get('filter_type', '')
        return redirect(url_for('investments', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type))

    filter_goal = request.args.get('filter_goal', '')
    filter_account = request.args.get('filter_account', '')
    filter_type = request.args.get('filter_type', '')
    return render_template('investments/edit_investment.html', investment=investment, filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type)

@app.route('/investments/delete/<int:id>')
def delete_investment(id):
    investment = Investment.query.get_or_404(id)
    Transaction.query.filter_by(investment_id=id).delete()
    db.session.delete(investment)
    db.session.commit()
    filter_goal = request.args.get('filter_goal', '')
    filter_account = request.args.get('filter_account', '')
    filter_type = request.args.get('filter_type', '')
    return redirect(url_for('investments', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type))

@app.route('/investments/transactions/<int:investment_id>', methods=['GET', 'POST'])
def transactions(investment_id):
    investment = Investment.query.get_or_404(investment_id)
    
    if request.method == 'POST':
        date_str = request.form['date']
        amount = float(request.form['amount'])
        notes = request.form.get('notes', '')
        
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        transaction = Transaction(
            date=date,
            amount=amount,
            investment_id=investment.id,
            notes=notes
        )
        
        investment.total_amount += amount
        
        db.session.add(transaction)
        db.session.commit()
        
        return redirect(url_for('transactions', investment_id=investment.id))
    
    transactions = Transaction.query.filter_by(investment_id=investment_id).order_by(Transaction.date.desc()).all()
    return render_template(
        'investments/transactions.html', 
        investment=investment, 
        transactions=transactions,
        datetime=datetime
    )

@app.route('/investments/update_actual_amount/<int:id>', methods=['POST'])
def update_actual_amount(id):
    investment = Investment.query.get_or_404(id)
    actual_amount = float(request.form['actual_amount'])
    investment.actual_amount = actual_amount
    db.session.commit()
    filter_goal = request.form.get('filter_goal', '')
    filter_account = request.form.get('filter_account', '')
    filter_type = request.form.get('filter_type', '')
    return redirect(url_for('investments', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type))

@app.route('/update_market_value', methods=['POST'])
def update_market_value():
    account_name = request.form['account_name']
    market_value = float(request.form['market_value'])

    # Create or update a special portfolio entry for non-stock investments
    portfolio = Portfolio.query.filter_by(account=account_name, symbol='NON-STOCK').first()

    if not portfolio:
        portfolio = Portfolio(
            symbol='NON-STOCK',
            shares=1,
            average_price=market_value,
            latest_price=market_value,
            account=account_name
        )
        db.session.add(portfolio)
    else:
        portfolio.average_price = market_value
        portfolio.latest_price = market_value

    db.session.commit()
    filter_goal = request.form.get('filter_goal', '')
    filter_account = request.form.get('filter_account', '')
    filter_type = request.form.get('filter_type', '')
    return redirect(url_for('investments', filter_goal=filter_goal, filter_account=filter_account, filter_type=filter_type))
    
@app.route('/portfolio')
def portfolio():
    portfolios = Portfolio.query.filter(Portfolio.symbol != 'NON-STOCK').all()
    # Update latest prices from stock data
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        for p in portfolios:
            latest_price = pd.read_sql('''
                SELECT close FROM stocks 
                WHERE symbol = ? 
                ORDER BY date DESC 
                LIMIT 1
            ''', conn, params=(p.symbol,))['close'].iloc[0] if pd.read_sql('''
                SELECT COUNT(*) as count FROM stocks 
                WHERE symbol = ?
            ''', conn, params=(p.symbol,))['count'].iloc[0] > 0 else None
            
            if latest_price:
                p.latest_price = latest_price
                db.session.commit()
    
    investments = Investment.query.all()
    return render_template('portfolio/index.html', 
                         portfolios=portfolios,
                         investments=investments,
                         now=datetime.now)

@app.route('/portfolio/add', methods=['GET', 'POST'])
def add_portfolio():
    investments = Investment.query.all()
    
    # Get all available symbols from the stock database
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        symbols = pd.read_sql('SELECT DISTINCT symbol FROM stocks ORDER BY symbol', conn)['symbol'].tolist()
    
    if request.method == 'POST':
        symbol = request.form['symbol'].upper()
        shares = float(request.form['shares'])
        average_price = float(request.form['average_price'])
        account = request.form['account']
        investment_id = request.form.get('investment_id')
        
        portfolio = Portfolio(
            symbol=symbol,
            shares=shares,
            average_price=average_price,
            account=account,
            investment_id=investment_id if investment_id else None
        )
        
        db.session.add(portfolio)
        db.session.commit()
        
        return redirect(url_for('portfolio'))
    
    return render_template('portfolio/add.html', 
                         investments=investments,
                         symbols=symbols)

@app.route('/portfolio/edit/<int:id>', methods=['GET', 'POST'])
def edit_portfolio(id):
    portfolio = Portfolio.query.get_or_404(id)
    investments = Investment.query.all()
    
    # Get all available symbols from the stock database
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        symbols = pd.read_sql('SELECT DISTINCT symbol FROM stocks ORDER BY symbol', conn)['symbol'].tolist()  # Changed from .tolists() to .tolist()
    
    filter_symbol = request.args.get('filter_symbol', '')
    filter_account = request.args.get('filter_account', '')

    if request.method == 'POST':
        portfolio.symbol = request.form['symbol'].upper()
        portfolio.shares = float(request.form['shares'])
        portfolio.average_price = float(request.form['average_price'])
        portfolio.account = request.form['account']
        portfolio.investment_id = request.form.get('investment_id')

        filter_symbol = request.form.get('filter_symbol', '')
        filter_account = request.form.get('filter_account', '')

        db.session.commit()
        return redirect(url_for('portfolio', filter_symbol=filter_symbol, filter_account=filter_account))

    return render_template('portfolio/edit.html',
                         portfolio=portfolio,
                         investments=investments,
                         symbols=symbols,
                         filter_symbol=filter_symbol,
                         filter_account=filter_account)

@app.route('/portfolio/delete/<int:id>')
def delete_portfolio(id):
    portfolio = Portfolio.query.get_or_404(id)
    filter_symbol = request.args.get('filter_symbol', '')
    filter_account = request.args.get('filter_account', '')
    db.session.delete(portfolio)
    db.session.commit()
    return redirect(url_for('portfolio', filter_symbol=filter_symbol, filter_account=filter_account))

@app.route('/portfolio/update_prices')
def update_prices():
    portfolios = Portfolio.query.all()
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        for p in portfolios:
            latest_price = pd.read_sql('''
                SELECT close FROM stocks 
                WHERE symbol = ? 
                ORDER BY date DESC 
                LIMIT 1
            ''', conn, params=(p.symbol,))['close'].iloc[0] if pd.read_sql('''
                SELECT COUNT(*) as count FROM stocks 
                WHERE symbol = ?
            ''', conn, params=(p.symbol,))['count'].iloc[0] > 0 else None
            
            if latest_price:
                p.latest_price = latest_price
                db.session.commit()
    
    return redirect(url_for('portfolio'))

@app.route('/my-stocks')
def my_stocks():
    # Query all portfolios from the database, excluding NON-STOCK
    portfolios = Portfolio.query.filter(Portfolio.symbol != 'NON-STOCK').all()
    
    # Update latest prices from stock data
    with sqlite3.connect(app.config['STOCK_DATABASE']) as conn:
        for p in portfolios:
            latest_price = pd.read_sql('''
                SELECT close FROM stocks 
                WHERE symbol = ? 
                ORDER BY date DESC 
                LIMIT 1
            ''', conn, params=(p.symbol,))['close'].iloc[0] if pd.read_sql('''
                SELECT COUNT(*) as count FROM stocks 
                WHERE symbol = ?
            ''', conn, params=(p.symbol,))['count'].iloc[0] > 0 else None
            
            if latest_price:
                p.latest_price = latest_price
                db.session.commit()
    
    # Aggregate portfolio data by symbol
    stocks = {}
    for portfolio in portfolios:
        symbol = portfolio.symbol
        if symbol not in stocks:
            stocks[symbol] = {
                'symbol': symbol,
                'total_shares': 0,
                'total_cost': 0,
                'market_value': 0,
                'profit': 0
            }
        
        stocks[symbol]['total_shares'] += portfolio.shares
        stocks[symbol]['total_cost'] += portfolio.total_cost
        stocks[symbol]['market_value'] += portfolio.market_value
        stocks[symbol]['profit'] += portfolio.profit
    
    # Calculate average price for each symbol
    for symbol, data in stocks.items():
        if data['total_shares'] > 0:
            data['average_price'] = data['total_cost'] / data['total_shares']
        else:
            data['average_price'] = 0
        
        # Use the latest price from any portfolio entry for this symbol
        for portfolio in portfolios:
            if portfolio.symbol == symbol and portfolio.latest_price:
                data['latest_price'] = portfolio.latest_price
                break
        else:
            data['latest_price'] = 0
    
    return render_template('mystocks.html', stocks=list(stocks.values()), now=datetime.now)
    
@app.route('/set-theme/<theme>')
def set_theme(theme):
    response = make_response(redirect(url_for('index')))
    response.set_cookie('theme', theme, max_age=60*60*24*30)  # 30 days
    return response

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8443, ssl_context=('ssl/server.crt', 'ssl/server.key'))
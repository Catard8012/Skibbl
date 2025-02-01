from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random

# Initialize Flask app and SocketIO
app = Flask(__name__)
socketio = SocketIO(app)

# Game state variables
players = []
current_drawer_index = -1
round_number = 1
round_started = False
word_selection_active = False
current_word = ""

# List of words to draw
word_list = ["apple", "banana", "cat", "dog", "elephant"]

@app.route('/game')
def game():
    return render_template('game.html')

@socketio.on('chat_message')
def handle_chat_message(data):
    global round_started, current_drawer_index, current_word

    username = data.get('username', 'Unknown')
    message = str(data.get('message', '')).strip()
    correct = False

    if message.lower() == current_word.lower():  # Check if the guess is correct
        correct = True
        drawer_session_id = players[current_drawer_index]['session_id']
        if request.sid != drawer_session_id:  # Ensure the drawer is not guessing
            # Notify all players of the correct guess and reveal the word
            socketio.emit('reveal_word', {'word': current_word})

            # Optionally, assign points to the player who guessed correctly
            for player in players:
                if player['session_id'] == request.sid:
                    player['points'] += 10  # Adjust points as needed
                    break

            # End the round and start a new one if all non-drawers guess correctly
            non_drawers = [player for player in players if player['session_id'] != drawer_session_id]
            if all(player['points'] > 0 for player in non_drawers):  # All non-drawers guessed correctly
                socketio.emit('end_round')  # End the round
                round_started = False  # Reset round state
                start_round()  # Start a new round

    # Broadcast the message to all users
    socketio.emit('chat_message', {
        'username': username,
        'message': message if not correct else f"#{current_word}",  # Un-hashtag the correct word
        'correct': correct
    })

@socketio.on('join_game')
def handle_join_game(data):
    username = data['username']
    session_id = request.sid  # Get the session ID of the user

    # Check if the player is already in the game by username or session_id
    existing_player = next((player for player in players if player['name'] == username), None)
    if existing_player:
        # If player with the same name already exists, prevent them from joining and notify them
        emit('error', {'message': 'You already have a tab open!'})
        return

    # Add player to the game
    players.append({'name': username, 'session_id': session_id, 'points': 0})
    emit('update_players', players, broadcast=True)

    # If there's only 1 player, tell them we need more players to start the round
    if len(players) == 1:
        socketio.emit('waiting_for_players', {'message': 'Waiting for more players to join...'}, room=session_id)
        socketio.emit('remove_drawers', {'message': 'Waiting for more players to start drawing.'}, room=session_id)

    # Start a new round if there are 2 or more players
    if len(players) >= 2 and not round_started:
        start_round()

def start_round():
    global current_drawer_index, round_started, word_selection_active

    if round_started or word_selection_active:
        return

    word_selection_active = True  # Mark word selection as active

    # Start from the last player in the list initially, then move upwards
    if current_drawer_index == -1:
        current_drawer_index = len(players) - 1  # Start from the bottom player
    else:
        current_drawer_index = (current_drawer_index - 1) % len(players)  # Move upwards

    drawer = players[current_drawer_index]
    word_options = random.sample(word_list, 3)

    for player in players:
        is_drawer = player['session_id'] == drawer['session_id']
        socketio.emit('start_word_selection', {
            'drawer': drawer['name'],
            'wordOptions': word_options if is_drawer else None,
            'timer': 10
        }, room=player['session_id'])

@socketio.on('word_selected')
def handle_word_selected(data):
    global round_started

    word = data['word']
    set_word(word)
    round_started = True

    # Notify all clients to remove the waiting box
    socketio.emit('end_word_selection')

    # Notify all clients of the new round
    for player in players:
        drawer = players[current_drawer_index]
        is_drawer = player['session_id'] == drawer['session_id']
        underscores = '_ ' * len(word)  # Generate correct number of underscores
        socketio.emit('new_round', {
            'drawer': drawer['name'],
            'word': word if is_drawer else underscores.strip(),  # Remove trailing space
            'word_length': len(word),  # Send correct word length
            'players': players
        }, room=player['session_id'])

    # Start the round timer immediately
    socketio.emit('start_round_timer', {'timer': 30}, to=None)

def set_word(word):
    global current_word
    current_word = word

@socketio.on('end_word_selection')
def handle_end_word_selection():
    global round_started, current_drawer_index, word_selection_active

    if round_started:
        return

    print("Debug: Word selection timer ended, assigning random word")
    drawer = players[current_drawer_index]
    random_word = random.choice(word_list)
    set_word(random_word)

    # Notify all clients to remove the word selection UI
    socketio.emit('end_word_selection')

    # Notify all players of the new round
    for player in players:
        is_drawer = player['session_id'] == drawer['session_id']
        underscores = '_ ' * len(random_word)
        socketio.emit('new_round', {
            'drawer': drawer['name'],
            'word': random_word if is_drawer else underscores.strip(),
            'word_length': len(random_word),
            'players': players
        }, room=player['session_id'])

    round_started = True
    word_selection_active = False
    socketio.emit('start_round_timer', {'timer': 30}, to=None)

@socketio.on('end_round')
def handle_end_round():
    global round_started, current_drawer_index, word_selection_active

    round_started = False
    socketio.emit('round_ended', to=None)

    # Move to the next drawer in the list (cycle through the players)
    current_drawer_index = (current_drawer_index + 1) % len(players)
    word_selection_active = False

    # Immediately start the next round
    start_round()

@socketio.on('drawing')
def handle_drawing(data):
    emit('drawing_data', data, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    global players

    # Remove the player from the game when they disconnect
    disconnected_player = next((player for player in players if player['session_id'] == request.sid), None)
    if disconnected_player:
        players.remove(disconnected_player)
        emit('update_players', players, broadcast=True)

        # If only 1 player is left, send "waiting for players" message and remove drawers
        if len(players) == 1:
            socketio.emit('waiting_for_players', {'message': 'Waiting for more players to join...'}, room=players[0]['session_id'])
            socketio.emit('remove_drawers', {'message': 'Waiting for more players to start drawing.'}, room=players[0]['session_id'])

        print(f"Player {disconnected_player['name']} disconnected.")

if __name__ == '__main__':
    socketio.run(app, debug=True)

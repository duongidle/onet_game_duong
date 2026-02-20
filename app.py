import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit
from collections import deque

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

ROOMS = {}

ROWS = 9
COLS = 16
TILE_TYPES = 36
SCORE_PER_MATCH = 20


# ================= ROOM =================

def generate_room_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_board():
    total = ROWS * COLS
    pairs = total // 2
    tiles = []

    for i in range(pairs):
        tiles += [i % TILE_TYPES, i % TILE_TYPES]

    random.shuffle(tiles)

    board = []
    idx = 0
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            row.append(tiles[idx])
            idx += 1
        board.append(row)

    return board


# ================= PIKACHU PATHFIND =================
def can_connect(board, a, b):
    if a == b: return None
    r1, c1 = a; r2, c2 = b
    if board[r1][c1] != board[r2][c2]: return None

    # LẤY KÍCH THƯỚC ĐỘNG TỪ BOARD THỰC TẾ
    R = len(board)
    C = len(board[0]) # Cột có thể khác Hàng

    # Tạo board padding
    padded = [[None] * (C + 2)]
    for row in board:
        padded.append([None] + row[:] + [None])
    padded.append([None] * (C + 2))

    # Chuyển tọa độ sang hệ tọa độ padded
    r1, c1, r2, c2 = r1 + 1, c1 + 1, r2 + 1, c2 + 1

    directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
    
    # Khởi tạo visited với giá trị đủ lớn
    visited = [[[3] * 4 for _ in range(C + 2)] for _ in range(R + 2)]
    q = deque()

    # Bước đi đầu tiên từ ô nguồn
    for d, (dr, dc) in enumerate(directions):
        nr, nc = r1 + dr, c1 + dc
        # Biên kiểm tra phải là R+2 và C+2
        if 0 <= nr < R + 2 and 0 <= nc < C + 2:
            if padded[nr][nc] is None or (nr, nc) == (r2, c2):
                visited[nr][nc][d] = 0
                q.append((nr, nc, d, 0, [(r1-1, c1-1), (nr-1, nc-1)]))

    while q:
        r, c, d, turns, path = q.popleft()

        if (r, c) == (r2, c2):
            return path

        for nd, (dr, dc) in enumerate(directions):
            nr, nc = r + dr, c + dc
            
            # ĐIỀU KIỆN QUAN TRỌNG: nr, nc phải chạy được đến R+1 và C+1
            if 0 <= nr < R + 2 and 0 <= nc < C + 2:
                nturns = turns + (1 if nd != d else 0)
                
                if nturns <= 2:
                    if padded[nr][nc] is None or (nr, nc) == (r2, c2):
                        if nturns < visited[nr][nc][nd]:
                            visited[nr][nc][nd] = nturns
                            q.append((nr, nc, nd, nturns, path + [(nr-1, nc-1)]))
    return None

# ================= COLLAPSE =================

def apply_collapse(board, mode):
    if not board or not board[0]:
        return

    R = len(board)
    C = len(board[0])

    if mode == "down":
        for c in range(C):
            col = [board[r][c] for r in range(R) if board[r][c] is not None]
            new_col = [None] * (R - len(col)) + col
            for r in range(R):
                board[r][c] = new_col[r]

    elif mode == "up":
        for c in range(C):
            col = [board[r][c] for r in range(R) if board[r][c] is not None]
            new_col = col + [None] * (R - len(col))
            for r in range(R):
                board[r][c] = new_col[r]

    elif mode == "left":
        for r in range(R):
            row = [x for x in board[r] if x is not None]
            new_row = row + [None] * (C - len(row))
            board[r] = new_row

    elif mode == "right":
        for r in range(R):
            row = [x for x in board[r] if x is not None]
            new_row = [None] * (C - len(row)) + row
            board[r] = new_row

    elif mode == "zigzag":
        for c in range(C):
            col = [board[r][c] for r in range(R) if board[r][c] is not None]
            if c % 2 == 0:
                new_col = [None] * (R - len(col)) + col
            else:
                new_col = col + [None] * (R - len(col))
            for r in range(R):
                board[r][c] = new_col[r]



# ================= RESHUFFLE =================

def available_pairs(board):
    R = len(board)
    C = len(board[0])
    pairs=[]

    for r1 in range(R):
        for c1 in range(C):
            if board[r1][c1] is None:
                continue
            for r2 in range(R):
                for c2 in range(C):
                    if (r1,c1)<(r2,c2) and board[r1][c1]==board[r2][c2]:
                        if can_connect(board,(r1,c1),(r2,c2)):
                            pairs.append(((r1,c1),(r2,c2)))
    return pairs


def reshuffle_if_needed(board):
    R = len(board)
    C = len(board[0])

    while True:
        pairs=available_pairs(board)
        if len(pairs)>=3:
            return

        flat=[x for row in board for x in row if x is not None]
        random.shuffle(flat)

        idx=0
        for r in range(R):
            for c in range(C):
                if board[r][c] is not None:
                    board[r][c]=flat[idx]
                    idx+=1


# ================= ROUTE =================

@app.route("/")
def index():
    return render_template("index.html")


# ================= SOCKET =================

@socketio.on("create_room")
def handle_create_room(data):
    name = data.get("name")
    if not name:
        return

    room_id = generate_room_id()
    board = generate_board()

    ROOMS[room_id] = {
        "board": board,
        "players": [request.sid],
        "names": {request.sid: name},
        "scores": {request.sid: 0},
        "locked": False,
        "collapse_mode": random.choice(["down","up","left","right","zigzag"])
    }

    join_room(room_id)

    emit("room_created", {"room": room_id})


@socketio.on("join_room_request")
def handle_join_room(data):
    room_id = data.get("room")
    name = data.get("name")

    if room_id not in ROOMS:
        emit("room_error", {"msg": "Room không tồn tại"})
        return

    if ROOMS[room_id]["locked"] or len(ROOMS[room_id]["players"]) >= 2:
        emit("room_error", {"msg": "Phòng đã đủ người"})
        return

    join_room(room_id)

    ROOMS[room_id]["players"].append(request.sid)
    ROOMS[room_id]["names"][request.sid] = name
    ROOMS[room_id]["scores"][request.sid] = 0
    ROOMS[room_id]["locked"] = True

    emit("start_game", {
        "board": ROOMS[room_id]["board"],
        "players": ROOMS[room_id]["names"],
        "scores": ROOMS[room_id]["scores"],
        "room": room_id
    }, room=room_id)

@socketio.on("disconnect")
def handle_disconnect():
    for room_id, room in list(ROOMS.items()):
        players = room["players"]

        if request.sid in players:
            # Xóa người vừa thoát
            players.remove(request.sid)

            # Nếu còn 1 người → ép out
            if len(players) == 1:
                remaining_sid = players[0]

                emit("force_exit", {
                    "msg": "Đối thủ đã thoát. Phòng bị hủy."
                }, room=remaining_sid)

            # Xóa phòng luôn
            del ROOMS[room_id]
            break

# ================= GAME =================

@socketio.on("select")
def select(data):
    room=data["room"]
    a=tuple(data["a"])
    b=tuple(data["b"])

    board=ROOMS[room]["board"]
    path=can_connect(board,a,b)

    if path:
        board[a[0]][a[1]]=None
        board[b[0]][b[1]]=None

        ROOMS[room]["scores"][request.sid]+=SCORE_PER_MATCH

        apply_collapse(board, ROOMS[room]["collapse_mode"])
        reshuffle_if_needed(board)

        emit("update",{
            "board":board,
            "scores":ROOMS[room]["scores"],
            "path":path,
            "removed":[a,b]
        },room=room)

        if all(all(cell is None for cell in row) for row in board):
            emit("game_over",ROOMS[room]["scores"],room=room)


@socketio.on("restart")
def restart(data):
    room=data["room"]
    ROOMS[room]["board"]=generate_board()
    ROOMS[room]["collapse_mode"] = random.choice(
        ["down","up","left","right","zigzag"]
    )

    for sid in ROOMS[room]["scores"]:
        ROOMS[room]["scores"][sid]=0

    emit("start_game",{
        "board":ROOMS[room]["board"],
        "players":ROOMS[room]["names"],
        "scores":ROOMS[room]["scores"],
        "room":room
    },room=room)

if __name__=="__main__":
    socketio.run(app, host="0.0.0.0", port=5050, debug=False)
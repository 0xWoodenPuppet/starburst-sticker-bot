# ── DFS ──────────────────────────────────────
graph = {
    'A': ['B', 'C'],
    'B': ['D'],
    'C': ['E'],
    'D': [],
    'E': [],
}

def dfs(node, visited=set()):
    if node in visited: return
    print(node, end=' ')
    visited.add(node)
    for neighbor in graph[node]:
        dfs(neighbor)

dfs('A')  # A B D C E

# ── BFS ──────────────────────────────────────
from collections import deque

graph = {
    'A': ['B', 'C'],
    'B': ['D'],
    'C': ['E'],
    'D': [],
    'E': [],
}

def bfs(start):
    visited, queue = {start}, deque([start])
    while queue:
        node = queue.popleft()
        print(node, end=' ')
        for neighbor in graph[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

bfs('A')  # A B C D E

# ── MINIMAX ───────────────────────────────────
import math

values    = [3, 5, 2, 9]           
max_depth = int(math.log2(len(values)))

def minimax(depth, index, is_max):
    if depth == max_depth:
        return values[index]
    left  = minimax(depth + 1, index * 2,     not is_max)
    right = minimax(depth + 1, index * 2 + 1, not is_max)
    return max(left, right) if is_max else min(left, right)

print(minimax(0, 0, True))  # 5
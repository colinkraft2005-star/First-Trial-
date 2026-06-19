import requests

# The player stats API endpoint you tracked down
data_url = 'https://barttorvik.com/getadvstats.php?year=2026&specialSource=0&conyes=0&start=20251101&end=20260501&top=365&xvalue=All&page=playerstat&team='

# Make the request
response = requests.get(data_url)

# Convert the raw database string directly into a Python list
player_data = response.json()

# Let's count how many total players were scraped
print(f"Total players found: {len(player_data)}")

# Print out the very first player row to see how the numbers are arranged
print("\n--- FIRST PLAYER RAW RECORDFILE ---")
print(player_data[0])
# ... keep your existing requests and player_data setup above ...

print("--- CLEANED PLAYER LIST ---")

# Loop through the first 20 players to test the output format cleanly
for player in player_data[:20]:
    name = player[0]
    team = player[1]
    conference = player[2]
    year = player[22]
    height = player[23]

    print(f"Name: {name} | Team: {team} ({conference}) | Class: {year} | HT: {height}")
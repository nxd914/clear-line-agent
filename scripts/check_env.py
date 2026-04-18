import os
from dotenv import load_dotenv
load_dotenv()
print('Loaded API key:', os.environ.get('KALSHI_API_KEY'))

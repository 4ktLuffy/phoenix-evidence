"""Live check of `phoenix-evidence doctor` against a local Phoenix (:6006) with dataset splits.

    uv run --extra phoenix python bench/doctor_live.py
    phoenix-evidence --url http://localhost:6006 doctor <printed name> --splits train,test

Uploads four examples: one copied across train and test with opposite labels. Output of the run:
results/doctor_live.json.
"""

import uuid

import pandas as pd
from phoenix.client import Client

c = Client(base_url='http://localhost:6006')
long = 'the customer asked for a refund on order 88 because the parcel arrived damaged and the box was open; ' * 3
df = pd.DataFrame(
    [
        {'q': long, 'label': 'pass', 'split': 'train'},
        {'q': long, 'label': 'fail', 'split': 'test'},
        {
            'q': 'an unrelated question about opening hours on public holidays in the main store',
            'label': 'pass',
            'split': 'test',
        },
        {
            'q': 'what is the warranty period for the blue kettle bought online last spring',
            'label': 'fail',
            'split': 'train',
        },
    ]
)
name = f'doctor-live-{uuid.uuid4().hex[:6]}'
c.datasets.create_dataset(name=name, dataframe=df, input_keys=['q'], output_keys=['label'], split_keys=['split'])
print(name)

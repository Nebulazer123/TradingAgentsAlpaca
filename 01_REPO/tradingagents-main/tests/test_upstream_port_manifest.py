from pathlib import Path


def test_manifest_tracks_every_selected_commit():
    text = Path("docs/upstream/tauric-v0.3.1-port-manifest.md").read_text()
    selected = {
        "b47a828",
        "daf1da9",
        "7df18fc",
        "ee1ece3",
        "9fd54f8",
        "3570f2e",
        "9ad98c5",
        "517eeaf",
        "0405168",
        "622f99d",
        "a0120e1",
        "eeb84aa",
        "308757c",
        "a102afa",
        "ddfb840",
        "db05903",
        "43bd32b",
        "a420ad0",
    }
    assert all(commit in text for commit in selected)
    assert "01477f9afb7a47b849ed4c9259d3a9a4738d9fda" in text

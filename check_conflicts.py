import yaml
import pandas as pd


def check_conflicts(file_path):
    with open(file_path, "r") as file:
        data = yaml.safe_load(file)
    df = pd.DataFrame(data["deployment"])
    df = df.T
    df["max_count"] = df["flavor"].apply(lambda x: data["nodes_inventory"][x])
    df["node"] = df.index

    training_df = df[df["node"].str.startswith("training-")]
    if not training_df.empty:
        training_df = training_df.reset_index()
        training_df["date"] = training_df.apply(
            lambda x: pd.date_range(start=x["start"], end=x["end"]), axis=1
        )
        training_df = training_df.explode("date")
        training_df = training_df.groupby(["flavor", "date"]).agg(
            {"count": "sum", "max_count": "first", "node": "unique"}
        )
        training_df = training_df.reset_index()
        training_df["conflict"] = (
            training_df["count"] > training_df["max_count"]
        )

    not_training_df = df[~df["node"].str.startswith("training-")]
    not_training_df = not_training_df.groupby("flavor").agg(
        {"count": "sum", "max_count": "first", "node": "unique"}
    )
    not_training_df = not_training_df.reset_index()
    not_training_df["conflict"] = (
        not_training_df["count"] > not_training_df["max_count"]
    )
    
    df = pd.concat([training_df, not_training_df]) if not training_df.empty and not not_training_df.empty else training_df if not training_df.empty else not_training_df

    df["node"] = df["node"].apply(lambda x: ", ".join(x))

    conflicts = []
    for _, row in df[df["conflict"]].iterrows():
        date = (
            f"on {row['date'].strftime('%Y-%m-%d')} "
            if not pd.isnull(row["date"])
            else ""
        )
        conflicts.append(
            f"Conflict for {row['flavor']} {date}with {row['count']} nodes requested but only {row['max_count']} available. Conflicted nodes: {row['node']}."
        )

    conflicts = "\n".join(conflicts)
    if conflicts:
        raise ValueError(f"Conflicts found:\n{conflicts}")
    else:
        return True


if __name__ == "__main__":
    check_conflicts("resources.yaml")

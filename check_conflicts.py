import yaml
import pandas as pd

def check_conflicts(file_path):
    with open(file_path, "r") as file:
        data = yaml.safe_load(file)
    df = pd.DataFrame(data["deployment"]).T
    df["node"] = df.index

    # Separate workers and trainings
    worker_df = df[~df["node"].str.startswith("training-")]
    training_df = df[df["node"].str.startswith("training-")]

    # Calculate available nodes per flavor
    worker_counts = worker_df.groupby("flavor")["count"].sum().to_dict()
    available_nodes = {flavor: data["nodes_inventory"][flavor] - worker_counts.get(flavor, 0) for flavor in data["nodes_inventory"]}

    conflicts = []
    if not training_df.empty:
        # Counting frequency of training nodes per day
        training_df = training_df.reset_index()
        training_df["date"] = training_df.apply(
            lambda x: pd.date_range(start=x["start"], end=x["end"]), axis=1
        )
        training_df = training_df.explode("date")
        grouped = training_df.groupby(["flavor", "date"]).agg(
            {"count": "sum", "node": "unique"}
        ).reset_index()
        # Check requested training nodes against available nodes
        grouped["available_nodes"] = grouped["flavor"].map(available_nodes).fillna(0)
        grouped["conflict"] = grouped["count"] > grouped["available_nodes"]
        grouped["node"] = grouped["node"].apply(lambda x: ", ".join(x))
        for _, row in grouped[grouped["conflict"]].iterrows():
            conflicts.append(
                f"Conflict for {row['flavor']} on {row['date'].strftime('%Y-%m-%d')} with {row['count']} training nodes requested but only {row['available_nodes']} available nodes. Conflicted trainings: {row['node']}."
            )

    if conflicts:
        raise ValueError("Conflicts found:\n" + "\n".join(conflicts))
    else:
        return True

if __name__ == "__main__":
    check_conflicts("resources.yaml")


import typer

app = typer.Typer()


@app.command()
def main(name: str):
    print(f"Hello {name}")
    exit(0)


if __name__ == "__main__":
    app()

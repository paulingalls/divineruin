class CreatureSeedConnection:
    def __init__(self) -> None:
        self.creatures: set[str] = set()

    async def execute(self, query: str, *args: str) -> None:
        if "INSERT INTO creatures" in query:
            key, _ = args
            self.creatures.add(key)

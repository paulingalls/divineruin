Bump: patch

Fixed: an Unbound player whose patron was stored as empty, rather than "none", made the twenty-minute deed judgment fail, which stopped that session's background loop. Such players are now judged as Unbound and earn autonomy normally. A patron id that names no god still fails loudly.

Release steps: none.

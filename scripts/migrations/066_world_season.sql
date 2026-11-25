INSERT INTO world_flags (flag_name, data)
VALUES ('season', '{"value":"spring"}')
ON CONFLICT (flag_name) DO NOTHING;

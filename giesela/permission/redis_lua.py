"""Custom Lua snippets for Redis"""

from giesela.utils import RedisCode

__all__ = ["REDIS_HAS_PERMISSION", "REDIS_HAS_ALL_PERMISSIONS", "REDIS_ANY_TARGET_HAS_ROLE", "REDIS_DEL_NS"]

# language=lua
REDIS_HAS_PERMISSION = RedisCode(b"""
local prefix = ARGV[1]
local perm = ARGV[2]

for _, target in ipairs(KEYS) do
    local roles = redis.call("LRANGE", prefix .. ":targets:" .. target, 0, -1)

    if roles then
        for _, role in ipairs(roles) do
            local role_key = prefix .. ":roles:" .. role .. ":permissions"
            local has_perm = redis.call("HGET", role_key, perm)

            if has_perm then return has_perm end
        end
    end
end
""")

# language=lua
REDIS_HAS_ALL_PERMISSIONS = RedisCode(b"""
local prefix = table.remove(ARGV, 1)
local perms = ARGV

for _, target in ipairs(KEYS) do
    local roles = redis.call("LRANGE", prefix .. ":targets:" .. target, 0, -1)

    if roles then
        for _, role in ipairs(roles) do
            local role_key = prefix .. ":roles:" .. role .. ":permissions"
            local has_perms = redis.call("HMGET", role_key, unpack(perms))

            for i = #has_perms, 1, -1 do
                local has_perm = has_perms[i]

                if has_perm == "1" then
                    table.remove(perms, i)
                elseif has_perm == "0" then
                    return "0"
                end
            end

            if next(perms) == nil then
                return "1"
            end
        end
    end
end

return "0"
""")

# language=lua
REDIS_ANY_TARGET_HAS_ROLE = RedisCode(b"""
local target_role_id = ARGV[1]

for _, target in ipairs(KEYS) do
    local roles = redis.call("LRANGE", target, 0, -1)

    if roles then
        for _, role_id in ipairs(roles) do
            if role_id == target_role_id then
                return "1"
            end
        end
    end
end

return "0"
""")

# language=lua
REDIS_DEL_NS = RedisCode(b"""
redis.replicate_commands()

for _, target in ipairs(ARGV) do
    local cursor = "0"

    repeat
        local result = redis.call("SCAN", cursor, "MATCH", target)
        cursor = result[1]
        local keys = result[2]

        if #keys > 0 then
            redis.call("DEL", unpack(keys))
        end
    until (cursor == "0")
end
""")

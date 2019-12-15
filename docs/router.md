# Giesela Router

## Public Realm

The public realm deviates a bit from the WAMP protocol in order to fully support Giesela's permission system.


### Authentication

There are three auth roles: "api", "multi-user", and "user".

### API
The api role is used for sessions providing Giesela's procedures.
It can do whatever and isn't bound to a user.

#### Multi-User
The multi-user role is for sessions representing multiple, or rather *all* users. 
It can perform actions on behalf of any user, but is still limited by the user it is representing.

#### User
The user role is for sessions representing a single user. It can only perform actions on behalf of the user it is representing.

##### Authentication
User authentication is done using [Discord OAuth2 tokens](https://discordapp.com/developers/docs/topics/oauth2).


### Authorization

This entire section doesn't apply to sessions with the api role.
The api role requires no authorization to perform any action.

Sessions can only perform the following actions:
- Call
- Cancel
- Subscribe
- Unsubscribe

Trying to perform another action will cause an error.

> In the future this might even cause a disconnect, but currently there is no way to do this.

### Calls

The realm **only** performs rate-limiting.
Permissions must be checked by the callee.

### Events

Sessions can subscribe to any topic, but they will only receive an event if conditions are met.
Publishers can specify the following constraints in the details:

| key         | type         | description
| ----------- | ------------ | -----------
| guild_id    | snowflake    | If set, only users of that guild will receive the event.
| user_id     | snowflake    | If set, only the specified user will receive the event.
| permissions | permission[] | Only users with the permissions will receive the event.

These constraints **only** apply to sessions with the **user role**.
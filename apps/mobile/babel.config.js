// Legacy Hermes needs this syntax profile alongside the SDK 56 Hermes V1 opt-out in app.json.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [["babel-preset-expo", { unstable_transformProfile: "hermes-v0" }]],
  };
};

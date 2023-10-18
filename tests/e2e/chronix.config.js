module.exports = {
  engine: {
    port: 8080,
  },
  commands: {
    test: 'poetry run pytest tests -m integration',
  },
  plugins: ['simple-dvt-v1'],
};

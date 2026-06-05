# Frontend image: Vite dev server (single-page app, no router).
FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173
# --host exposes the dev server outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

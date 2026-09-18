FROM node:26.7.0-alpine

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3081 \
    DATA_DIR=/data

WORKDIR /app
COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src
RUN mkdir -p /data && chown node:node /data

USER node
EXPOSE 3081
VOLUME ["/data"]
CMD ["npm", "start"]

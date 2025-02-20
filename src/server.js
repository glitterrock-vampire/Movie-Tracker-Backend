require("dotenv").config();
const express = require("express");
const cors = require("cors");
const sequelize = require("./config/database");

const app = express();
app.use(cors());
app.use(express.json());

// Test Route
app.get("/", (req, res) => res.send("Movie Tracker API is running..."));

// Connect to Database
sequelize.authenticate()
    .then(() => console.log("Database connected..."))
    .catch(err => console.log("Error: " + err));

const PORT = process.env.PORT || 5001;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));

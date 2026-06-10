SELECT COUNT(DISTINCT Language) FROM countrylanguage
SELECT min(Number_products), max(Number_products) FROM shop
SELECT Name FROM conductor ORDER BY Year_of_Work DESC
SELECT Name, Country, Age FROM singer ORDER BY Age DESC
SELECT COUNT(DISTINCT Location) FROM shop
SELECT COUNT(DISTINCT T1.department_id) FROM Degree_Programs AS T1 INNER JOIN Departments AS T2 ON T1.department_id = T2.department_id
SELECT date_arrived, date_departed FROM Dogs
SELECT Name, SurfaceArea FROM country ORDER BY SurfaceArea DESC LIMIT 5
SELECT count(*) FROM Templates
SELECT charge_type, MAX(charge_amount) FROM Charges GROUP BY charge_type ORDER BY MAX(charge_amount) DESC LIMIT 1
SELECT DISTINCT T1.breed_code, T2.size_code FROM Breeds AS T1 INNER JOIN Dogs AS T3 ON T1.breed_code = T3.breed_code INNER JOIN Sizes AS T2 ON T3.size_code = T2.size_code
SELECT vote_id, phone_number, state FROM VOTES
SELECT T1.Name, COUNT(T2.concert_ID) FROM stadium AS T1 JOIN concert AS T2 ON T1.Stadium_ID = T2.Stadium_ID GROUP BY T1.Stadium_ID
SELECT COUNT(*) FROM country WHERE Continent = 'Asia'
SELECT zip_postcode FROM Addresses WHERE city = "Port Chelsea"
SELECT Citizenship FROM singer GROUP BY Citizenship ORDER BY COUNT(*) DESC LIMIT 1
SELECT StuID, COUNT(PetID) FROM Has_Pet GROUP BY StuID
SELECT T1.Name FROM conductor AS T1 JOIN orchestra AS T2 ON T1.Conductor_ID = T2.Conductor_ID GROUP BY T1.Name ORDER BY COUNT(DISTINCT T2.Orchestra_ID) DESC LIMIT 1
SELECT Language, COUNT(id) FROM TV_Channel GROUP BY Language ORDER BY COUNT(id) ASC LIMIT 1
SELECT T2.City FROM flights AS T1 JOIN airports AS T2 ON T1.SourceAirport = T2.AirportCode GROUP BY T2.City ORDER BY COUNT(*) DESC LIMIT 1
SELECT T2.Template_Type_Code FROM Documents AS T1 JOIN Templates AS T2 ON T1.Template_ID = T2.Template_ID WHERE T1.Document_Name = "Data base"
SELECT SUM(Population) FROM city WHERE District = 'Gelderland'
SELECT Name FROM people WHERE Nationality != "Russia"
SELECT DISTINCT Country FROM singer WHERE Age > 20
SELECT COUNT(*) FROM flights AS T1 JOIN airports AS T2 ON T1.DestAirport = T2.AirportCode WHERE T2.City = 'Aberdeen' OR T2.City = 'Abilene'
SELECT COUNT(*) FROM flights AS T1 JOIN airports AS T2 ON T1.DestAirport = T2.AirportCode WHERE T1.Airline = 'United Airlines' AND T2.City = 'Aberdeen'
SELECT email_address FROM Professionals WHERE state = "Hawaii" OR state = "Wisconsin"
SELECT T1.professional_id, T1.cell_number FROM Professionals AS T1 JOIN Treatments AS T2 ON T1.professional_id = T2.professional_id GROUP BY T1.professional_id HAVING COUNT(DISTINCT T2.treatment_type_code) > 1
SELECT T1.Year_of_Founded FROM orchestra AS T1 JOIN performance AS T2 ON T1.Orchestra_ID = T2.Orchestra_ID GROUP BY T1.Orchestra_ID HAVING COUNT(T2.Performance_ID) > 1
SELECT Nationality FROM people GROUP BY Nationality HAVING COUNT(*) >= 2
SELECT DISTINCT T1.Model FROM model_list AS T1 INNER JOIN car_makers AS T2 ON T1.Maker = T2.Id INNER JOIN car_names AS T3 ON T1.Model = T3.Model INNER JOIN cars_data AS T4 ON T3.MakeId = T4.Id WHERE T2.FullName = 'General Motors' OR T4.Weight > 3500
SELECT SUM(SurfaceArea) FROM country WHERE Continent IN ('Asia', 'Europe')
SELECT T1.professional_id, T1.role_code, T1.first_name FROM Professionals AS T1 JOIN Treatments AS T2 ON T1.professional_id = T2.professional_id GROUP BY T1.professional_id HAVING COUNT(*) >= 2
SELECT T1.Maker FROM car_makers AS T1 JOIN model_list AS T2 ON T1.Id = T2.Maker JOIN car_names AS T3 ON T2.Model = T3.Model JOIN cars_data AS T4 ON T3.MakeId = T4.Id WHERE T4.Year = 1970
SELECT T2.CountryName FROM countries AS T1 JOIN car_makers AS T2 ON T1.CountryId = T2.Country JOIN continents AS T3 ON T1.Continent = T3.ContId WHERE T3.Continent = 'Europe' GROUP BY T2.CountryName HAVING COUNT(*) >= 3
SELECT GovernmentForm, SUM(Population) FROM country WHERE GovernmentForm IN (SELECT GovernmentForm FROM country GROUP BY GovernmentForm HAVING AVG(LifeExpectancy) > 72) GROUP BY GovernmentForm
SELECT T1.Make, T2.Year FROM car_names AS T1 INNER JOIN cars_data AS T2 ON T1.MakeId = T2.Id ORDER BY T2.Year ASC LIMIT 1
SELECT COUNT(*) FROM cars_data WHERE Accelerate > (SELECT MAX(Horsepower) FROM cars_data)
SELECT Template_Type_Code FROM Ref_Template_Types WHERE Template_Type_Code NOT IN (SELECT Template_Type_Code FROM Templates WHERE Template_ID IN (SELECT Template_ID FROM Documents))
SELECT T1.Code FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE T2.Language != 'English' AND T1.GovernmentForm != 'Republic'
SELECT T1.name, T1.result, T1.bulgarian_commander FROM battle AS T1 JOIN ship AS T2 ON T1.id = T2.lost_in_battle WHERE T2.location != 'English Channel'
SELECT Orchestra FROM orchestra WHERE Orchestra_ID NOT IN (SELECT Orchestra_ID FROM performance)
SELECT COUNT(*) FROM battle WHERE id NOT IN (SELECT lost_in_battle FROM ship WHERE tonnage = '225')
SELECT Major, Age FROM Student WHERE StuID NOT IN (SELECT T1.StuID FROM Has_Pet AS T1 JOIN Pets AS T2 ON T1.PetID = T2.PetID WHERE T2.PetType = "Cat")
SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE (T2.Language = "English" OR T2.Language = "Dutch") AND T2.IsOfficial = "T"
SELECT Name FROM shop WHERE Shop_ID NOT IN (SELECT Shop_ID FROM hiring)
SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE T2.Language = "English" AND T1.Code IN (SELECT T1.Code FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE T2.Language = "French" AND T2.IsOfficial = 1) AND T2.IsOfficial = 1
SELECT COUNT(*) FROM Dogs WHERE age < (SELECT AVG(age) FROM Dogs)
SELECT COUNT(*) FROM cars_data WHERE Accelerate > (SELECT MAX(Horsepower) FROM cars_data)
SELECT AVG(GNP), SUM(Population) FROM country WHERE Code2 = 'US'

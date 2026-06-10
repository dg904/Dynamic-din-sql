SELECT COUNT(DISTINCT Language) FROM countrylanguage
SELECT MIN(Number_products), MAX(Number_products) FROM shop
SELECT Name FROM conductor ORDER BY Year_of_Work DESC
SELECT Name, Country, Age FROM singer ORDER BY Age DESC
SELECT COUNT(DISTINCT Location) FROM shop
SELECT COUNT(DISTINCT T1.department_id) FROM Degree_Programs AS T1 JOIN Departments AS T2 ON T1.department_id = T2.department_id
SELECT date_arrived, date_departed FROM Dogs
SELECT Name, SurfaceArea FROM country ORDER BY SurfaceArea DESC LIMIT 5
SELECT COUNT(*) FROM Templates
SELECT MAX(charge_amount) FROM Charges
SELECT T1.breed_name, T2.size_description FROM Breeds AS T1 JOIN Dogs AS T3 ON T1.breed_code = T3.breed_code JOIN Sizes AS T2 ON T3.size_code = T2.size_code
SELECT vote_id, phone_number, state FROM VOTES
SELECT T1.Name, COUNT(T2.concert_ID) FROM stadium AS T1 JOIN concert AS T2 ON T1.Stadium_ID = T2.Stadium_ID GROUP BY T1.Name
SELECT COUNT(*) FROM country WHERE Continent = 'Asia'
SELECT zip_postcode FROM Addresses WHERE city = 'Port Chelsea'
SELECT Citizenship FROM singer GROUP BY Citizenship ORDER BY COUNT(*) DESC LIMIT 1
SELECT T1.StuID, COUNT(T2.PetID) FROM Student AS T1 JOIN Has_Pet AS T2 ON T1.StuID = T2.StuID GROUP BY T1.StuID
SELECT T1.Name FROM conductor AS T1 JOIN orchestra AS T2 ON T1.Conductor_ID = T2.Conductor_ID GROUP BY T1.Conductor_ID ORDER BY COUNT(T2.Orchestra_ID) DESC LIMIT 1
SELECT Language, COUNT(*) FROM TV_Channel GROUP BY Language ORDER BY COUNT(*) ASC LIMIT 1
SELECT City FROM airports WHERE AirportCode = (SELECT SourceAirport FROM flights GROUP BY SourceAirport ORDER BY COUNT(*) DESC LIMIT 1)
SELECT T1.Template_Type_Code FROM Templates AS T1 JOIN Documents AS T2 ON T1.Template_ID = T2.Template_ID WHERE T2.Document_Name = 'Data base'
SELECT SUM(Population) FROM city WHERE District = 'Gelderland'
SELECT Name FROM people WHERE Nationality != 'Russia'
SELECT DISTINCT Country FROM singer WHERE Age > 20
SELECT COUNT(*) FROM flights AS T1 JOIN airports AS T2 ON T1.DestAirport = T2.AirportCode WHERE T2.City = 'Aberdeen' OR T2.City = 'Abilene'
SELECT COUNT(*) FROM flights AS T1 JOIN airports AS T2 ON T1.DestAirport = T2.AirportCode JOIN airlines AS T3 ON T1.Airline = T3.Abbreviation WHERE T2.City = 'Aberdeen' AND T3.Airline = 'United Airlines'
SELECT email_address FROM Professionals WHERE state = 'Hawaii' OR state = 'Wisconsin'
SELECT T1.professional_id, T1.cell_number FROM Professionals AS T1 JOIN Treatments AS T2 ON T1.professional_id = T2.professional_id GROUP BY T1.professional_id, T1.cell_number HAVING COUNT(DISTINCT T2.treatment_type_code) >= 2
SELECT T1.Year_of_Founded FROM orchestra AS T1 JOIN performance AS T2 ON T1.Orchestra_ID = T2.Orchestra_ID GROUP BY T1.Orchestra_ID HAVING COUNT(T2.Performance_ID) > 1
SELECT Nationality FROM people GROUP BY Nationality HAVING COUNT(People_ID) >= 2
SELECT DISTINCT T4.Model FROM car_makers AS T1 JOIN model_list AS T2 ON T1.Id = T2.Maker JOIN car_names AS T3 ON T2.Model = T3.Model JOIN cars_data AS T4 ON T3.MakeId = T4.Id WHERE T1.FullName = 'General Motors' OR T4.Weight > 3500
SELECT SUM(SurfaceArea) FROM country WHERE Continent IN ('Asia', 'Europe')
SELECT T1.professional_id, T1.role_code, T1.first_name FROM Professionals AS T1 JOIN Treatments AS T2 ON T1.professional_id = T2.professional_id GROUP BY T1.professional_id HAVING COUNT(T2.treatment_id) >= 2
SELECT T1.FullName FROM car_makers AS T1 JOIN model_list AS T2 ON T1.Id = T2.Maker JOIN car_names AS T3 ON T2.Model = T3.Model JOIN cars_data AS T4 ON T3.MakeId = T4.Id WHERE T4.Year = 1970
SELECT T1.CountryName FROM countries AS T1 JOIN car_makers AS T2 ON T1.CountryId = T2.Country JOIN continents AS T3 ON T1.Continent = T3.ContId WHERE T3.Continent = 'Europe' GROUP BY T1.CountryName HAVING COUNT(T2.Id) >= 3
SELECT GovernmentForm, SUM(Population) FROM country WHERE GovernmentForm IN (SELECT GovernmentForm FROM country GROUP BY GovernmentForm HAVING AVG(LifeExpectancy) > 72) GROUP BY GovernmentForm
SELECT T1.Make, T2.Year FROM car_names AS T1 JOIN cars_data AS T2 ON T1.MakeId = T2.Id WHERE T2.Year = (SELECT MIN(Year) FROM cars_data)
SELECT COUNT(*) FROM cars_data WHERE Accelerate > (SELECT MAX(Horsepower) FROM cars_data)
SELECT Template_Type_Code FROM Ref_Template_Types WHERE Template_Type_Code NOT IN (SELECT Template_Type_Code FROM Templates WHERE Template_ID IN (SELECT Template_ID FROM Documents))
SELECT Code FROM country WHERE GovernmentForm NOT LIKE '%Republic%' AND Code NOT IN (SELECT CountryCode FROM countrylanguage WHERE Language = 'English')
SELECT T1.name, T1.result, T1.bulgarian_commander FROM battle AS T1 LEFT JOIN ship AS T2 ON T1.id = T2.lost_in_battle WHERE T2.location != 'English Channel' OR T2.location IS NULL
SELECT Orchestra FROM orchestra WHERE Orchestra_ID NOT IN (SELECT Orchestra_ID FROM performance)
SELECT COUNT(*) FROM battle WHERE id NOT IN (SELECT lost_in_battle FROM ship WHERE tonnage = '225')
SELECT Major, Age FROM Student WHERE StuID NOT IN (SELECT T1.StuID FROM Has_Pet AS T1 JOIN Pets AS T2 ON T1.PetID = T2.PetID WHERE T2.PetType = 'cat')
SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE T2.IsOfficial = 'T' AND (T2.Language = 'English' OR T2.Language = 'Dutch')
SELECT Name FROM shop WHERE Shop_ID NOT IN (SELECT Shop_ID FROM hiring)
SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code = T2.CountryCode WHERE T2.Language = 'English' AND T1.Code IN (SELECT T3.CountryCode FROM countrylanguage AS T3 WHERE T3.Language = 'French' AND T3.IsOfficial = 'T') AND T2.IsOfficial = 'T'
SELECT COUNT(*) FROM Dogs WHERE age < (SELECT AVG(age) FROM Dogs)
SELECT COUNT(*) FROM cars_data WHERE Accelerate > (SELECT MAX(Horsepower) FROM cars_data)
SELECT AVG(GNP), SUM(Population) FROM country WHERE Code2 = 'US'
